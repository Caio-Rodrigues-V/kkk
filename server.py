import http.server
import socketserver
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import os
import sys
import threading
import concurrent.futures

# Ensure UTF-8 console output
sys.stdout.reconfigure(encoding='utf-8')

PORT = int(os.environ.get("PORT", 8000))
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")
RAW_CACHE_FILE = os.path.join(os.path.dirname(__file__), "raw_cache.json")
CACHE_EXPIRY_MINUTES = 15

# Try to load env variables from a local .env file if it exists (for local development)
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    except Exception as e:
        print("Warning: Could not parse .env file:", e)

# API Keys and tokens loaded from environment variables (Railway or .env)
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
META_AD_ACCOUNT = os.environ.get("META_AD_ACCOUNT")
META_IG_ACCOUNT = os.environ.get("META_IG_ACCOUNT")
META_VERSION = os.environ.get("META_VERSION", "v25.0")

DINX_API_KEY = os.environ.get("DINX_API_KEY")
DINX_LIST_URL = os.environ.get("DINX_LIST_URL", "https://bff.prd.dinx.app/site.beta_access.v1.SiteBetaAccessService/ListBetaAccess")

# Thread lock & state for background updates
fetch_lock = threading.Lock()
is_fetching = False

# Redis mapping functions
def fetch_redis_mapping():
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("REDIS_PUBLIC_URL")
    redis_host = os.environ.get("REDISHOST")
    redis_port = int(os.environ.get("REDISPORT", 6379))
    redis_password = os.environ.get("REDISPASSWORD") or os.environ.get("REDIS_PASSWORD")
    
    mapping = {}  # email/phone -> lead_id
    try:
        import redis
        conn = None
        if redis_url:
            print("Connecting to Redis via URL...")
            conn = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=5.0, socket_connect_timeout=5.0)
        elif redis_host:
            print(f"Connecting to Redis via host {redis_host}...")
            conn = redis.Redis(host=redis_host, port=redis_port, password=redis_password, decode_responses=True, socket_timeout=5.0, socket_connect_timeout=5.0)
        else:
            print("No Redis configuration found in environment variables.")
            return {}
            
        print("Scanning all keys in Redis...")
        keys = list(conn.scan_iter("*"))
        print(f"Found {len(keys)} keys in Redis. Fetching values in batches...")
        
        chunk_size = 1000
        for i in range(0, len(keys), chunk_size):
            chunk_keys = keys[i:i + chunk_size]
            vals = conn.mget(chunk_keys)
            
            for key, val_str in zip(chunk_keys, vals):
                if val_str:
                    try:
                        val = json.loads(val_str)
                        lead_id = val.get("lead_id")
                        payload = val.get("payload", {})
                        email = payload.get("email")
                        phone = val.get("phone_digits") or payload.get("phone")
                        
                        if lead_id:
                            if email:
                                mapping[email.lower().strip()] = lead_id
                            if phone:
                                clean_phone = "".join(filter(str.isdigit, str(phone)))
                                if len(clean_phone) >= 10:
                                    mapping[clean_phone[-11:]] = lead_id
                    except:
                        pass
        print(f"Loaded {len(mapping)} mappings from Redis.")
    except Exception as e:
        print("Error fetching from Redis:", e)
    return mapping

GLOBAL_FORM_LEADS_CACHE = {}

def fetch_meta_leads_by_ids(lead_ids):
    """Fetch campaign_id, adset_id, ad_id for a list of lead_ids using Meta Graph API batching."""
    mappings = {}
    try:
        chunk_size = 50
        for i in range(0, len(lead_ids), chunk_size):
            chunk = list(lead_ids)[i:i+chunk_size]
            ids_str = ",".join(str(x) for x in chunk)
            url = f"https://graph.facebook.com/{META_VERSION}/?ids={ids_str}&fields=id,campaign_id,adset_id,ad_id,field_data&access_token={META_ACCESS_TOKEN}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for l_id, lead in data.items():
                    c_id = lead.get("campaign_id")
                    a_id = lead.get("adset_id")
                    ad_id = lead.get("ad_id")
                    
                    email = ""
                    phone = ""
                    for fd in lead.get("field_data", []):
                        fname = fd.get("name", "").lower()
                        fd_vals = fd.get("values")
                        if not fd_vals or not isinstance(fd_vals, list):
                            continue
                        if "email" in fname:
                            email = str(fd_vals[0]).lower().strip()
                        elif "phone" in fname or "celular" in fname or "telefone" in fname or "whatsapp" in fname or "wpp" in fname:
                            phone = "".join(filter(str.isdigit, str(fd_vals[0])))
                            
                    mappings[str(l_id)] = {
                        "campaign_id": c_id,
                        "adset_id": a_id,
                        "ad_id": ad_id,
                        "source": "meta_lead_id"
                    }
                    if email:
                        mappings[email] = mappings[str(l_id)]
                    if phone and len(phone) >= 10:
                        mappings[phone[-11:]] = mappings[str(l_id)]
    except Exception as e:
        print("Error fetching meta leads by ids:", e)
    return mappings

def fetch_meta_form_leads(form_ids):
    global GLOBAL_FORM_LEADS_CACHE
    new_mappings = {}
    if not form_ids:
        return GLOBAL_FORM_LEADS_CACHE.copy()
        
    for form_id in form_ids:
        try:
            url = f"https://graph.facebook.com/{META_VERSION}/{form_id}/leads?fields=id,campaign_id,adset_id,ad_id,field_data&limit=500&access_token={META_ACCESS_TOKEN}"
            pages_fetched = 0
            while url and pages_fetched < 100:  # limit to max 50000 leads per form
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    data = res.get("data", [])
                    if not data:
                        break
                        
                    has_overlap = False
                    for lead in data:
                        l_id = lead.get("id")
                        c_id = lead.get("campaign_id")
                        a_id = lead.get("adset_id")
                        ad_id = lead.get("ad_id")
                        
                        email = ""
                        phone = ""
                        for fd in lead.get("field_data", []):
                            fname = fd.get("name", "").lower()
                            if "email" in fname:
                                fd_vals = fd.get("values")
                                if fd_vals and isinstance(fd_vals, list) and len(fd_vals) > 0:
                                    email = str(fd_vals[0]).lower().strip()
                            elif "phone" in fname or "celular" in fname or "telefone" in fname or "whatsapp" in fname or "wpp" in fname:
                                fd_vals = fd.get("values")
                                if fd_vals and isinstance(fd_vals, list) and len(fd_vals) > 0:
                                    raw_phone = str(fd_vals[0])
                                    phone = "".join(filter(str.isdigit, raw_phone))
                                
                        if l_id:
                            new_mappings[l_id] = {
                                "campaign_id": c_id,
                                "adset_id": a_id,
                                "ad_id": ad_id,
                                "form_id": form_id,
                                "source": "meta_form_lead"
                            }
                            if email:
                                new_mappings[email] = {
                                    "campaign_id": c_id,
                                    "adset_id": a_id,
                                    "ad_id": ad_id,
                                    "form_id": form_id,
                                    "source": "meta_form_lead"
                                }
                            if phone and len(phone) >= 10:
                                new_mappings[phone[-11:]] = {
                                    "campaign_id": c_id,
                                    "adset_id": a_id,
                                    "ad_id": ad_id,
                                    "form_id": form_id,
                                    "source": "meta_form_lead"
                                }
                            if l_id in GLOBAL_FORM_LEADS_CACHE:
                                has_overlap = True
                                
                    if has_overlap:
                        break
                        
                    paging = res.get("paging", {})
                    url = paging.get("next")
                    pages_fetched += 1
        except Exception as e:
            print(f"Error fetching leads for form {form_id}:", e)
            
    GLOBAL_FORM_LEADS_CACHE.update(new_mappings)
    print(f"Form leads cache size: {len(GLOBAL_FORM_LEADS_CACHE)} (added {len(new_mappings)} in this sync).")
    return GLOBAL_FORM_LEADS_CACHE.copy()

def extract_lead_form_ids(value):
    form_ids = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in ("lead_gen_form_id", "leadgen_form_id", "lead_form_id") and item:
                form_ids.add(str(item))
            else:
                form_ids.update(extract_lead_form_ids(item))
    elif isinstance(value, list):
        for item in value:
            form_ids.update(extract_lead_form_ids(item))
    return form_ids

def discover_meta_lead_form_ids(ads_meta):
    form_ids = set()
    for ad in ads_meta.values():
        form_ids.update(extract_lead_form_ids(ad))
    return form_ids

def get_campaign_for_lead(lead_id, form_leads_mapping):
    if lead_id in form_leads_mapping:
        val = form_leads_mapping[lead_id]
        if isinstance(val, dict):
            return val.get("campaign_id")
        return val
    return None

# Cache for custom Meta API queries (to avoid hitting Meta API repeatedly for the same dates)
CUSTOM_META_CACHE = {}  # Key: "start_date:end_date", Value: (timestamp, campaigns_list)
CUSTOM_META_DAILY_SPEND_CACHE = {}  # Key: "start_date:end_date", Value: (timestamp, daily_spend_list)
CUSTOM_META_CACHE_EXPIRY = timedelta(minutes=15)

def fetch_meta_campaigns_metadata():
    campaigns_meta = {}
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT:
        print("Skipping Meta Campaigns metadata fetch: META_ACCESS_TOKEN or META_AD_ACCOUNT is not configured.")
        return campaigns_meta
    try:
        url = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/campaigns?fields=name,status,effective_status,objective&limit=5000&access_token={META_ACCESS_TOKEN}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            for c in res.get("data", []):
                campaigns_meta[c["id"]] = c
    except Exception as e:
        print("Error fetching Meta Campaigns metadata:", e)
    return campaigns_meta

def fetch_meta_adsets_metadata():
    adsets_meta = {}
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT:
        print("Skipping Meta Adsets metadata fetch: META_ACCESS_TOKEN or META_AD_ACCOUNT is not configured.")
        return adsets_meta
    try:
        url = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/adsets?fields=name,status,effective_status,campaign_id&limit=5000&access_token={META_ACCESS_TOKEN}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            for a in res.get("data", []):
                adsets_meta[a["id"]] = a
    except Exception as e:
        print("Error fetching Meta Adsets metadata:", e)
    return adsets_meta

def fetch_meta_ads_metadata():
    ads_meta = {}
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT:
        print("Skipping Meta Ads metadata fetch: META_ACCESS_TOKEN or META_AD_ACCOUNT is not configured.")
        return ads_meta
    try:
        url = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/ads?fields=name,status,effective_status,campaign_id,adset_id,creative{{thumbnail_url}}&limit=5000&access_token={META_ACCESS_TOKEN}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            for a in res.get("data", []):
                ads_meta[a["id"]] = a
    except Exception as e:
        print("Error fetching Meta Ads metadata:", e)
    return ads_meta

def get_custom_meta_campaigns(start_date, end_date):
    key = f"{start_date}:{end_date}"
    now = datetime.now()
    if key in CUSTOM_META_CACHE:
        cache_time, data = CUSTOM_META_CACHE[key]
        if now - cache_time < CUSTOM_META_CACHE_EXPIRY:
            print(f"Serving custom range Meta data for {key} from memory cache.")
            return data
            
    meta_campaigns = []
    try:
        campaigns_meta = fetch_meta_campaigns_metadata()
        time_range = urllib.parse.quote(json.dumps({"since": start_date, "until": end_date}))
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=campaign&fields=campaign_name,campaign_id,spend,impressions,clicks,actions,cpc,ctr&time_range={time_range}&limit=1000&access_token={META_ACCESS_TOKEN}"
        req_i = urllib.request.Request(url_i, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_i, timeout=15.0) as resp:
            insights_res = json.loads(resp.read().decode("utf-8"))
            meta_insights = insights_res.get("data", [])
            
        for item in meta_insights:
            c_id = item.get("campaign_id")
            meta_info = campaigns_meta.get(c_id, {})
            
            leads = 0
            for action in item.get("actions", []):
                if action.get("action_type") == "lead":
                    leads = int(action.get("value", 0))
                    break
                    
            meta_campaigns.append({
                "id": c_id,
                "name": item.get("campaign_name"),
                "status": meta_info.get("status", "PAUSED"),
                "effective_status": meta_info.get("effective_status", "PAUSED"),
                "objective": meta_info.get("objective", "OUTCOME"),
                "spend": float(item.get("spend", 0.0)),
                "impressions": int(item.get("impressions", 0)),
                "clicks": int(item.get("clicks", 0)),
                "ctr": float(item.get("ctr", 0.0)),
                "cpc": float(item.get("cpc", 0.0)),
                "leads": leads
            })
        print(f"Fetched {len(meta_campaigns)} campaigns for custom range {start_date} to {end_date}.")
        CUSTOM_META_CACHE[key] = (now, meta_campaigns)
    except Exception as e:
        print(f"Error fetching Meta Ads data for custom range {start_date} to {end_date}:", e)
        
    return meta_campaigns

def fetch_meta_campaigns(preset, campaigns_meta):
    meta_campaigns = []
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT:
        print(f"Skipping Meta Ads data fetch for preset '{preset}': META_ACCESS_TOKEN or META_AD_ACCOUNT is not configured.")
        return meta_campaigns
    try:
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=campaign&fields=campaign_name,campaign_id,spend,impressions,clicks,actions,cpc,ctr&date_preset={preset}&limit=500&access_token={META_ACCESS_TOKEN}"
        req_i = urllib.request.Request(url_i, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_i, timeout=15.0) as resp:
            insights_res = json.loads(resp.read().decode("utf-8"))
            meta_insights = insights_res.get("data", [])
            
        for item in meta_insights:
            c_id = item.get("campaign_id")
            meta_info = campaigns_meta.get(c_id, {})
            
            leads = 0
            for action in item.get("actions", []):
                if action.get("action_type") == "lead":
                    leads = int(action.get("value", 0))
                    break
                    
            meta_campaigns.append({
                "id": c_id,
                "name": item.get("campaign_name"),
                "status": meta_info.get("status", "PAUSED"),
                "effective_status": meta_info.get("effective_status", "PAUSED"),
                "objective": meta_info.get("objective", "OUTCOME"),
                "spend": float(item.get("spend", 0.0)),
                "impressions": int(item.get("impressions", 0)),
                "clicks": int(item.get("clicks", 0)),
                "ctr": float(item.get("ctr", 0.0)),
                "cpc": float(item.get("cpc", 0.0)),
                "leads": leads
            })
        print(f"Fetched {len(meta_campaigns)} campaigns for preset '{preset}'.")
    except Exception as e:
        print(f"Error fetching Meta Ads data for preset '{preset}':", e)
    return meta_campaigns

def fetch_meta_adsets(preset, adsets_meta):
    adsets = []
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT:
        print(f"Skipping Meta Ads adsets fetch for preset '{preset}': META_ACCESS_TOKEN or META_AD_ACCOUNT is not configured.")
        return adsets
    try:
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=adset&fields=adset_id,spend,impressions,clicks,actions&date_preset={preset}&limit=500&access_token={META_ACCESS_TOKEN}"
        req_i = urllib.request.Request(url_i, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_i, timeout=15.0) as resp:
            insights_res = json.loads(resp.read().decode("utf-8"))
            insights_data = insights_res.get("data", [])
            
        for item in insights_data:
            a_id = item.get("adset_id")
            meta_info = adsets_meta.get(a_id, {})
            if not meta_info:
                continue
            
            leads = 0
            for action in item.get("actions", []):
                if action.get("action_type") == "lead":
                    leads = int(action.get("value", 0))
                    break
                    
            adsets.append({
                "id": a_id,
                "name": meta_info.get("name"),
                "status": meta_info.get("status", "PAUSED"),
                "effective_status": meta_info.get("effective_status", "PAUSED"),
                "campaign_id": meta_info.get("campaign_id"),
                "spend": float(item.get("spend", 0.0)),
                "impressions": int(item.get("impressions", 0)),
                "clicks": int(item.get("clicks", 0)),
                "leads": leads
            })
        print(f"Fetched {len(adsets)} adsets for preset '{preset}'.")
    except Exception as e:
        print(f"Error fetching Meta Ads adsets for preset '{preset}':", e)
    return adsets

def fetch_meta_ads(preset, ads_meta):
    ads = []
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT:
        print(f"Skipping Meta Ads ads fetch for preset '{preset}': META_ACCESS_TOKEN or META_AD_ACCOUNT is not configured.")
        return ads
    try:
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=ad&fields=ad_id,spend,impressions,clicks,actions&date_preset={preset}&limit=500&access_token={META_ACCESS_TOKEN}"
        req_i = urllib.request.Request(url_i, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_i, timeout=15.0) as resp:
            insights_res = json.loads(resp.read().decode("utf-8"))
            insights_data = insights_res.get("data", [])
            
        for item in insights_data:
            ad_id = item.get("ad_id")
            meta_info = ads_meta.get(ad_id, {})
            if not meta_info:
                continue
                
            leads = 0
            for action in item.get("actions", []):
                if action.get("action_type") == "lead":
                    leads = int(action.get("value", 0))
                    break
                    
            creative = meta_info.get("creative", {})
            thumbnail_url = creative.get("thumbnail_url", "")
            
            ads.append({
                "id": ad_id,
                "name": meta_info.get("name"),
                "status": meta_info.get("status", "PAUSED"),
                "effective_status": meta_info.get("effective_status", "PAUSED"),
                "campaign_id": meta_info.get("campaign_id"),
                "adset_id": meta_info.get("adset_id"),
                "thumbnail_url": thumbnail_url,
                "spend": float(item.get("spend", 0.0)),
                "impressions": int(item.get("impressions", 0)),
                "clicks": int(item.get("clicks", 0)),
                "leads": leads
            })
        print(f"Fetched {len(ads)} ads for preset '{preset}'.")
    except Exception as e:
        print(f"Error fetching Meta Ads ads for preset '{preset}':", e)
    return ads

CUSTOM_META_ADSETS_CACHE = {}
def get_custom_meta_adsets(start_date, end_date):
    key = f"{start_date}:{end_date}"
    now = datetime.now()
    if key in CUSTOM_META_ADSETS_CACHE:
        cache_time, data = CUSTOM_META_ADSETS_CACHE[key]
        if now - cache_time < CUSTOM_META_CACHE_EXPIRY:
            return data
            
    adsets = []
    try:
        adsets_meta = fetch_meta_adsets_metadata()
        time_range = urllib.parse.quote(json.dumps({"since": start_date, "until": end_date}))
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=adset&fields=adset_id,spend,impressions,clicks,actions&time_range={time_range}&limit=500&access_token={META_ACCESS_TOKEN}"
        req_i = urllib.request.Request(url_i, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_i, timeout=15.0) as resp:
            insights_res = json.loads(resp.read().decode("utf-8"))
            insights_data = insights_res.get("data", [])
            
        for item in insights_data:
            a_id = item.get("adset_id")
            meta_info = adsets_meta.get(a_id, {})
            if not meta_info:
                continue
            
            leads = 0
            for action in item.get("actions", []):
                if action.get("action_type") == "lead":
                    leads = int(action.get("value", 0))
                    break
                    
            adsets.append({
                "id": a_id,
                "name": meta_info.get("name"),
                "status": meta_info.get("status", "PAUSED"),
                "effective_status": meta_info.get("effective_status", "PAUSED"),
                "campaign_id": meta_info.get("campaign_id"),
                "spend": float(item.get("spend", 0.0)),
                "impressions": int(item.get("impressions", 0)),
                "clicks": int(item.get("clicks", 0)),
                "leads": leads
            })
        print(f"Fetched {len(adsets)} adsets for custom range {start_date} to {end_date}.")
        CUSTOM_META_ADSETS_CACHE[key] = (now, adsets)
    except Exception as e:
        print(f"Error fetching Meta Ads adsets for custom range {start_date} to {end_date}:", e)
    return adsets

CUSTOM_META_ADS_CACHE = {}
def get_custom_meta_ads(start_date, end_date):
    key = f"{start_date}:{end_date}"
    now = datetime.now()
    if key in CUSTOM_META_ADS_CACHE:
        cache_time, data = CUSTOM_META_ADS_CACHE[key]
        if now - cache_time < CUSTOM_META_CACHE_EXPIRY:
            return data
            
    ads = []
    try:
        ads_meta = fetch_meta_ads_metadata()
        time_range = urllib.parse.quote(json.dumps({"since": start_date, "until": end_date}))
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=ad&fields=ad_id,spend,impressions,clicks,actions&time_range={time_range}&limit=150&access_token={META_ACCESS_TOKEN}"
        req_i = urllib.request.Request(url_i, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_i, timeout=15.0) as resp:
            insights_res = json.loads(resp.read().decode("utf-8"))
            insights_data = insights_res.get("data", [])
            
        for item in insights_data:
            ad_id = item.get("ad_id")
            meta_info = ads_meta.get(ad_id, {})
            if not meta_info:
                continue
                
            leads = 0
            for action in item.get("actions", []):
                if action.get("action_type") == "lead":
                    leads = int(action.get("value", 0))
                    break
                    
            creative = meta_info.get("creative", {})
            thumbnail_url = creative.get("thumbnail_url", "")
            
            ads.append({
                "id": ad_id,
                "name": meta_info.get("name"),
                "status": meta_info.get("status", "PAUSED"),
                "effective_status": meta_info.get("effective_status", "PAUSED"),
                "campaign_id": meta_info.get("campaign_id"),
                "adset_id": meta_info.get("adset_id"),
                "thumbnail_url": thumbnail_url,
                "spend": float(item.get("spend", 0.0)),
                "impressions": int(item.get("impressions", 0)),
                "clicks": int(item.get("clicks", 0)),
                "leads": leads
            })
        print(f"Fetched {len(ads)} ads for custom range {start_date} to {end_date}.")
        CUSTOM_META_ADS_CACHE[key] = (now, ads)
    except Exception as e:
        print(f"Error fetching Meta Ads ads for custom range {start_date} to {end_date}:", e)
    return ads

def fetch_meta_daily_spend(preset):
    daily_spend = []
    if not META_ACCESS_TOKEN or not META_AD_ACCOUNT:
        print(f"Skipping daily spend fetch for preset '{preset}': META_ACCESS_TOKEN or META_AD_ACCOUNT is not configured.")
        return daily_spend
    try:
        url_ds = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=account&fields=date_start,spend&time_increment=1&date_preset={preset}&limit=500&access_token={META_ACCESS_TOKEN}"
        req_ds = urllib.request.Request(url_ds, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_ds, timeout=15.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            for item in res.get("data", []):
                daily_spend.append({
                    "date": item.get("date_start"),
                    "spend": float(item.get("spend", 0.0))
                })
        print(f"Fetched {len(daily_spend)} daily spend records for preset '{preset}'.")
    except Exception as e:
        print(f"Error fetching daily spend for preset '{preset}':", e)
    return daily_spend

def get_custom_meta_daily_spend(start_date, end_date):
    key = f"{start_date}:{end_date}"
    now = datetime.now()
    if key in CUSTOM_META_DAILY_SPEND_CACHE:
        cache_time, data = CUSTOM_META_DAILY_SPEND_CACHE[key]
        if now - cache_time < CUSTOM_META_CACHE_EXPIRY:
            print(f"Returning cached custom Meta daily spend for {key}.")
            return data

    daily_spend = []
    try:
        time_range = urllib.parse.quote(json.dumps({"since": start_date, "until": end_date}))
        url_ds = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=account&fields=date_start,spend&time_increment=1&time_range={time_range}&limit=500&access_token={META_ACCESS_TOKEN}"
        req_ds = urllib.request.Request(url_ds, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_ds, timeout=15.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            for item in res.get("data", []):
                daily_spend.append({
                    "date": item.get("date_start"),
                    "spend": float(item.get("spend", 0.0))
                })
        print(f"Fetched {len(daily_spend)} daily spend records for custom range {start_date} to {end_date}.")
        CUSTOM_META_DAILY_SPEND_CACHE[key] = (now, daily_spend)
    except Exception as e:
        print(f"Error fetching custom daily spend for {start_date} to {end_date}:", e)
    return daily_spend


def fetch_raw_live_data():
    print(f"[{datetime.now().isoformat()}] Fetching live data from Dinx and Meta APIs...")
    
    # 1. Fetch Dinx leads (all 16,000+ items)
    dinx_requests = []
    if not DINX_API_KEY:
        print("Skipping Dinx data fetch: DINX_API_KEY is not configured.")
    else:
        try:
            req = urllib.request.Request(
                DINX_LIST_URL,
                data=json.dumps({}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": DINX_API_KEY,
                    "User-Agent": "Mozilla/5.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                dinx_res = json.loads(resp.read().decode("utf-8"))
                dinx_requests = dinx_res.get("requests", [])
                print(f"Fetched {len(dinx_requests)} leads from Dinx API.")
        except Exception as e:
            print("Error fetching Dinx data:", e)
        
    # 2. Fetch Meta Ads Campaigns, Adsets, and Ads for different presets
    meta_campaigns_by_preset = {}
    meta_adsets_by_preset = {}
    meta_ads_by_preset = {}
    meta_daily_spend_by_preset = {}
    
    # Fetch metadata once
    campaigns_meta = fetch_meta_campaigns_metadata()
    adsets_meta = fetch_meta_adsets_metadata()
    ads_meta = fetch_meta_ads_metadata()
    
    # Known historical forms plus any forms discovered in current ad creatives.
    known_form_ids = [
        "2230521901040318", # Form V5 (Ativo)
        "1047323807697738", # Desativado
        "2184251165469840", # Desativado
        "1594114028736919", # Desativado
        "803818399423508"   # Desativado
    ]
    discovered_form_ids = discover_meta_lead_form_ids(ads_meta)
    form_ids = sorted(set(known_form_ids).union(discovered_form_ids))
    print(f"Tracking lead generation forms: {form_ids} ({len(discovered_form_ids)} discovered from ads).")
    
    presets_map = {
        "all": "maximum",
        "7days": "last_7d",
        "30days": "last_30d",
        "thismonth": "this_month",
        "lastmonth": "last_month"
    }
    # Parallelize preset fetching to speed up loading
    def fetch_preset_data(preset_item):
        range_key, preset = preset_item
        return (
            range_key,
            fetch_meta_campaigns(preset, campaigns_meta),
            fetch_meta_adsets(preset, adsets_meta),
            fetch_meta_ads(preset, ads_meta),
            fetch_meta_daily_spend(preset)
        )
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        for range_key, c, ad, a, ds in executor.map(fetch_preset_data, presets_map.items()):
            meta_campaigns_by_preset[range_key] = c
            meta_adsets_by_preset[range_key] = ad
            meta_ads_by_preset[range_key] = a
            meta_daily_spend_by_preset[range_key] = ds

    # 3. Fetch Instagram profile & media
    ig_profile = {}
    ig_media = []
    if not META_ACCESS_TOKEN or not META_IG_ACCOUNT:
        print("Skipping Instagram data fetch: META_ACCESS_TOKEN or META_IG_ACCOUNT is not configured.")
    else:
        try:
            # Profile
            url_p = f"https://graph.facebook.com/{META_VERSION}/{META_IG_ACCOUNT}?fields=username,name,profile_picture_url,followers_count,media_count,biography,website&access_token={META_ACCESS_TOKEN}"
            req_p = urllib.request.Request(url_p, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_p, timeout=15.0) as resp:
                ig_profile = json.loads(resp.read().decode("utf-8"))

            # Media posts
            url_m = f"https://graph.facebook.com/{META_VERSION}/{META_IG_ACCOUNT}/media?fields=id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count,thumbnail_url&limit=50&access_token={META_ACCESS_TOKEN}"
            req_m = urllib.request.Request(url_m, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_m, timeout=15.0) as resp:
                ig_media_res = json.loads(resp.read().decode("utf-8"))
                ig_media = ig_media_res.get("data", [])

            print(f"Fetched {len(ig_media)} Instagram media items. Fetching insights in parallel...")

            def fetch_insights(m):
                media_type = m.get("media_type")
                if media_type == "VIDEO":
                    metrics_sets = [
                        "plays,reach,saved,shares,total_interactions",
                        "engagement,impressions,reach,saved,video_views"
                    ]
                elif media_type == "CAROUSEL_ALBUM":
                    metrics_sets = [
                        "carousel_album_engagement,carousel_album_impressions,carousel_album_reach,carousel_album_saved,carousel_album_video_views",
                        "engagement,impressions,reach,saved"
                    ]
                else:
                    metrics_sets = ["engagement,impressions,reach,saved"]

                for metrics in metrics_sets:
                    try:
                        url_ins = f"https://graph.facebook.com/{META_VERSION}/{m['id']}/insights?metric={metrics}&access_token={META_ACCESS_TOKEN}"
                        req_ins = urllib.request.Request(url_ins, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req_ins, timeout=10.0) as resp_ins:
                            ins_data = json.loads(resp_ins.read().decode("utf-8")).get("data", [])
                            for metric in ins_data:
                                name = metric.get("name")
                                values = metric.get("values", [])
                                if values:
                                    m[name] = values[0].get("value", 0)
                            return # Success
                    except Exception as e:
                        if hasattr(e, 'read'):
                            print(f"Insights Error ({media_type}) [{metrics}]:", e.read().decode('utf-8')[:200])
                        pass

            # Parallelize insights fetching (10 threads to avoid hitting rate limits too hard)
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                executor.map(fetch_insights, ig_media)

            print("Fetched Instagram profile and recent media with insights.")
        except Exception as e:
            print("Error fetching Instagram data:", e)
        
    # 4. Fetch Meta Form Leads based on discovered form IDs
    redis_mapping = fetch_redis_mapping()
    print(f"Fetching meta leads for forms: {form_ids}")
    form_leads_mapping = fetch_meta_form_leads(list(form_ids))
    
    # 5. Fetch details for any lead_ids found in redis that are not in the cache yet
    missing_lead_ids = [lid for lid in set(redis_mapping.values()) if str(lid) not in form_leads_mapping]
    if missing_lead_ids:
        print(f"Fetching details for {len(missing_lead_ids)} missing leads from Meta API...")
        missing_mappings = fetch_meta_leads_by_ids(missing_lead_ids)
        form_leads_mapping.update(missing_mappings)
        # Also update global cache
        GLOBAL_FORM_LEADS_CACHE.update(missing_mappings)
        
    return {
        "last_updated": datetime.now().isoformat(),
        "dinx_requests": dinx_requests,
        "meta_campaigns": meta_campaigns_by_preset,
        "meta_adsets": meta_adsets_by_preset,
        "meta_ads": meta_ads_by_preset,
        "meta_daily_spend": meta_daily_spend_by_preset,
        "ig_profile": ig_profile,
        "ig_media": ig_media,
        "redis_mapping": redis_mapping,
        "meta_form_ids": form_ids,
        "meta_discovered_form_ids": sorted(discovered_form_ids),
        "form_leads_mapping": form_leads_mapping
    }


def save_raw_cache(raw_data):
    try:
        with open(RAW_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving raw cache:", e)

def load_raw_cache():
    if os.path.exists(RAW_CACHE_FILE):
        try:
            with open(RAW_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print("Error reading raw cache:", e)
    return None

def start_background_fetch():
    global is_fetching
    with fetch_lock:
        if is_fetching:
            return
        is_fetching = True
        
    def run_fetch():
        global is_fetching
        try:
            print(f"[{datetime.now().isoformat()}] Starting background live data fetch...")
            raw_data = fetch_raw_live_data()
            save_raw_cache(raw_data)
            print(f"[{datetime.now().isoformat()}] Background live data fetch completed and cache saved.")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error in background live data fetch:", e)
        finally:
            is_fetching = False
            
    threading.Thread(target=run_fetch, daemon=True).start()

def is_internal_email(email):
    if not email:
        return False
    email = email.lower().strip()
    return "dinx.app" in email or "dinxapp.com" in email or "take" in email

def get_date_range_bounds(range_key, start_str=None, end_str=None):
    today = datetime.now()
    if range_key == "7days":
        start = today - timedelta(days=6)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), None
    elif range_key == "30days":
        start = today - timedelta(days=29)
        return start.replace(hour=0, minute=0, second=0, microsecond=0), None
    elif range_key == "thismonth":
        start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, None
    elif range_key == "lastmonth":
        first_of_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = first_of_this_month - timedelta(microseconds=1)
        start = (first_of_this_month - timedelta(days=15)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, end
    elif range_key == "custom":
        start = None
        end = None
        if start_str:
            try:
                start = datetime.strptime(start_str, "%Y-%m-%d")
            except:
                pass
        if end_str:
            try:
                end = datetime.strptime(end_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59, microsecond=999999)
            except:
                pass
        return start, end
    return None, None

def date_in_range(date_str, start_bound, end_bound):
    if not date_str:
        return False
    try:
        dt = datetime.fromisoformat(date_str[:19])
        if start_bound and dt < start_bound:
            return False
        if end_bound and dt > end_bound:
            return False
        return True
    except:
        return False

def date_str_in_range(day_str, start_bound, end_bound):
    try:
        dt = datetime.strptime(day_str, "%Y-%m-%d")
        if start_bound and dt < start_bound:
            return False
        if end_bound and dt > end_bound:
            return False
        return True
    except:
        return True

def get_processed_data(exclude_internal=False, date_range="all", start_date=None, end_date=None):
    # Load raw data from cache
    raw_data = load_raw_cache()
    
    # If no cache exists, trigger background fetch and return empty defaults
    if not raw_data:
        print("No raw cache found. Triggering background fetch...")
        start_background_fetch()
        return {
            "last_updated": None,
            "dinx_stats": {
                "total_leads": 0,
                "qualificados": 0,
                "qualificados_private": 0,
                "ativados": 0,
                "status_breakdown": {},
                "school_breakdown": {},
                "income_breakdown": {},
                "device_breakdown": {},
                "origin_breakdown": {},
                "daily_trend": []
            },
            "meta_stats": {
                "total_spend": 0.0,
                "lead_campaign_spend": 0.0,
                "profile_visit_spend": 0.0,
                "campaigns": [],
                "adsets": [],
                "ads": []
            },
            "ig_stats": {
                "profile": {},
                "media": []
            }
        }
    else:
        # Check if cache is expired (older than CACHE_EXPIRY_MINUTES)
        try:
            updated_time = datetime.fromisoformat(raw_data["last_updated"])
            if datetime.now() - updated_time >= timedelta(minutes=CACHE_EXPIRY_MINUTES):
                print("Cache expired. Triggering background fetch...")
                start_background_fetch()
        except Exception as e:
            print("Error checking cache expiry:", e)
            start_background_fetch()

    # Perform the aggregations and attribution calculation dynamically on the raw_data
    dinx_requests_raw = raw_data.get("dinx_requests", [])
    meta_campaigns_raw_all = raw_data.get("meta_campaigns", {})
    meta_adsets_raw_all = raw_data.get("meta_adsets", {})
    meta_ads_raw_all = raw_data.get("meta_ads", {})
    meta_daily_spend_raw_all = raw_data.get("meta_daily_spend", {})
    ig_profile = raw_data.get("ig_profile", {})
    ig_media = raw_data.get("ig_media", [])

    # Filter out internal emails if requested
    if exclude_internal:
        dinx_requests = [r for r in dinx_requests_raw if not is_internal_email(r.get("email"))]
    else:
        dinx_requests = list(dinx_requests_raw)

    # Calculate date range boundaries for Dinx leads
    start_bound, end_bound = get_date_range_bounds(date_range, start_date, end_date)

    # Load Meta Daily Spend
    meta_daily_spend_raw = []
    if date_range == "custom" and start_date and end_date:
        meta_daily_spend_raw = get_custom_meta_daily_spend(start_date, end_date)
    elif isinstance(meta_daily_spend_raw_all, dict):
        meta_daily_spend_raw = meta_daily_spend_raw_all.get(date_range, [])
    else:
        meta_daily_spend_raw = []
        
    daily_spend_map = {}
    for item in meta_daily_spend_raw:
        d_str = item.get("date")
        if d_str:
            daily_spend_map[d_str] = item.get("spend", 0.0)

    # 4. Aggregations & Calculations (Filtered by Date Range)
    dinx_totals = 0
    status_counts = {}
    school_counts = {}
    income_counts = {}
    device_counts = {}
    origin_counts = {}
    daily_registrations = {}
    
    qualificados_count = 0
    ativados_count = 0
    qualificados_private_count = 0
    
    # Process registrations, qualifications, and breakdowns in date range
    for r in dinx_requests:
        created_at = r.get("createdAt")
        status = r.get("status")
        school = r.get("schoolType")
        income = r.get("incomeRange")
        device = r.get("deviceType")
        origin = r.get("origin")
        
        is_qualificado = status in ["SITE_BETA_ACCESS_INVITE_STATUS_APPROVED", "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED"]
        is_ativado = (status == "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED" and school == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE")
        
        # Check if lead creation falls within date range for cohort breakdowns & registrations
        in_creation_range = date_in_range(created_at, start_bound, end_bound)
        
        # Check if activation falls within date range
        activated_at = r.get("activatedAt")
        act_date_str = activated_at if activated_at else created_at
        in_activation_range = date_in_range(act_date_str, start_bound, end_bound)
        
        if in_creation_range:
            dinx_totals += 1
            status_counts[status] = status_counts.get(status, 0) + 1
            school_counts[school] = school_counts.get(school, 0) + 1
            income_counts[income] = income_counts.get(income, 0) + 1
            device_counts[device] = device_counts.get(device, 0) + 1
            origin_counts[origin] = origin_counts.get(origin, 0) + 1
            
            if is_qualificado:
                qualificados_count += 1
                if school == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE":
                    qualificados_private_count += 1
                    
            # Registrations & Qualifications trends
            if created_at:
                day_str = created_at[:10]  # YYYY-MM-DD
                if day_str not in daily_registrations:
                    daily_registrations[day_str] = {"cadastros": 0, "qualificados": 0, "ativados": 0, "ativados_cohort": 0}
                daily_registrations[day_str]["cadastros"] += 1
                if is_qualificado:
                    daily_registrations[day_str]["qualificados"] += 1
                if is_ativado:
                    daily_registrations[day_str]["ativados_cohort"] += 1
                    
        # Activations are mapped to their actual activation date and checked against activation range
        if is_ativado and in_activation_range:
            ativados_count += 1
            if act_date_str:
                act_day_str = act_date_str[:10]
                if act_day_str not in daily_registrations:
                    daily_registrations[act_day_str] = {"cadastros": 0, "qualificados": 0, "ativados": 0, "ativados_cohort": 0}
                daily_registrations[act_day_str]["ativados"] += 1
                
    # Sort and filter daily registrations and spends by date
    sorted_daily = []
    all_days = set(daily_registrations.keys()).union(set(daily_spend_map.keys()))
    for day in sorted(all_days):
        if date_str_in_range(day, start_bound, end_bound):
            day_spend = daily_spend_map.get(day, 0.0)
            reg_info = daily_registrations.get(day, {"cadastros": 0, "qualificados": 0, "ativados": 0, "ativados_cohort": 0})
            day_qualificados = reg_info.get("qualificados", 0)
            day_cpl = (day_spend / day_qualificados) if day_qualificados > 0 else 0.0
            
            sorted_daily.append({
                "date": day,
                "cadastros": reg_info.get("cadastros", 0),
                "qualificados": day_qualificados,
                "ativados": reg_info.get("ativados", 0),
                "ativados_cohort": reg_info.get("ativados_cohort", 0),
                "spend": day_spend,
                "cpl": day_cpl
            })
        
    # 5. Campaign Attribution Logic (Dinx Backoffice to Meta lead forms)
    # Load Redis mapping (email/phone -> lead_id) from raw_data cache
    redis_mapping = raw_data.get("redis_mapping", {})
    
    # Load Meta form leads mapping (lead_id -> campaign_id) from raw_data cache
    form_leads_mapping = raw_data.get("form_leads_mapping", {})
    
    # Direct UTM campaign mapping: campaign_id -> { "leads": 0, "approved": 0, "activated": 0 }
    direct_campaigns = {}
    direct_adsets = {}
    direct_ads = {}
    
    # For attribution, we filter leads by range to match campaign dates
    for r in dinx_requests:
        created_at = r.get("createdAt")
        status = r.get("status")
        school = r.get("schoolType")
        email = r.get("email")
        phone = r.get("phone")
        
        is_qualificado = status in ["SITE_BETA_ACCESS_INVITE_STATUS_APPROVED", "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED"]
        is_ativado = (status == "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED" and school == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE")
        
        # Check if creation is in range
        in_creation_range = date_in_range(created_at, start_bound, end_bound)
        
        # Check if activation is in range
        activated_at = r.get("activatedAt")
        act_date_str = activated_at if activated_at else created_at
        in_activation_range = date_in_range(act_date_str, start_bound, end_bound)
        
        if not (in_creation_range or in_activation_range):
            continue
            
        c_id, a_id, ad_id = None, None, None
        lead_meta = None
        
        # 1. Direct Email Mapping from Meta Forms
        if email:
            lead_meta = form_leads_mapping.get(email.lower().strip())
            
        # 2. Direct Phone Mapping from Meta Forms API (Bypassing Redis)
        if not lead_meta and phone:
            clean_phone = "".join(filter(str.isdigit, str(phone)))
            if len(clean_phone) >= 10:
                lead_meta = form_leads_mapping.get(clean_phone[-11:])
                
        # 3. Try Redis mapping fallback (Phone -> Lead ID) if no direct match found
        if not lead_meta and phone:
            clean_phone = "".join(filter(str.isdigit, str(phone)))
            if len(clean_phone) >= 10:
                lead_id = redis_mapping.get(clean_phone[-11:])
                if lead_id:
                    lead_meta = form_leads_mapping.get(str(lead_id))
                    
        if lead_meta and isinstance(lead_meta, dict):
            c_id = lead_meta.get("campaign_id")
            a_id = lead_meta.get("adset_id")
            ad_id = lead_meta.get("ad_id")
                
        if c_id:
            if c_id not in direct_campaigns:
                direct_campaigns[c_id] = {"leads": 0, "approved": 0, "activated": 0}
            if in_creation_range:
                direct_campaigns[c_id]["leads"] += 1
                if is_qualificado:
                    direct_campaigns[c_id]["approved"] += 1
            if is_ativado and in_activation_range:
                direct_campaigns[c_id]["activated"] += 1
            
        if a_id:
            if a_id not in direct_adsets:
                direct_adsets[a_id] = {"leads": 0, "approved": 0, "activated": 0}
            if in_creation_range:
                direct_adsets[a_id]["leads"] += 1
                if is_qualificado:
                    direct_adsets[a_id]["approved"] += 1
            if is_ativado and in_activation_range:
                direct_adsets[a_id]["activated"] += 1
                
        if ad_id:
            if ad_id not in direct_ads:
                direct_ads[ad_id] = {"leads": 0, "approved": 0, "activated": 0}
            if in_creation_range:
                direct_ads[ad_id]["leads"] += 1
                if is_qualificado:
                    direct_ads[ad_id]["approved"] += 1
            if is_ativado and in_activation_range:
                direct_ads[ad_id]["activated"] += 1
                
    # Load Meta Campaigns for the requested date_range
    meta_campaigns_raw = []
    if date_range == "custom" and start_date and end_date:
        meta_campaigns_raw = get_custom_meta_campaigns(start_date, end_date)
    elif isinstance(meta_campaigns_raw_all, dict):
        meta_campaigns_raw = meta_campaigns_raw_all.get(date_range, [])
    else:
        # Fallback for old cache structure
        meta_campaigns_raw = meta_campaigns_raw_all if date_range == "all" else []
        
    meta_campaigns = []
    for c in meta_campaigns_raw:
        meta_campaigns.append(dict(c))

    # Enrich campaign list with attributed backoffice data (strictly direct)
    for c in meta_campaigns:
        c_id = c["id"]
        direct = direct_campaigns.get(c_id, {"leads": 0, "approved": 0, "activated": 0})
        c["dinx_leads"] = direct["leads"]
        c["dinx_approved"] = direct["approved"]
        c["dinx_activated"] = direct["activated"]

    # Load Meta Adsets for the requested date_range
    meta_adsets_raw = []
    if date_range == "custom" and start_date and end_date:
        meta_adsets_raw = get_custom_meta_adsets(start_date, end_date)
    elif isinstance(meta_adsets_raw_all, dict):
        meta_adsets_raw = meta_adsets_raw_all.get(date_range, [])
    else:
        meta_adsets_raw = []
        
    meta_adsets = []
    for a in meta_adsets_raw:
        meta_adsets.append(dict(a))
        
    for a in meta_adsets:
        a_id = a["id"]
        direct = direct_adsets.get(a_id, {"leads": 0, "approved": 0, "activated": 0})
        a["dinx_leads"] = direct["leads"]
        a["dinx_approved"] = direct["approved"]
        a["dinx_activated"] = direct["activated"]
        
    # Load Meta Ads for the requested date_range
    meta_ads_raw = []
    if date_range == "custom" and start_date and end_date:
        meta_ads_raw = get_custom_meta_ads(start_date, end_date)
    elif isinstance(meta_ads_raw_all, dict):
        meta_ads_raw = meta_ads_raw_all.get(date_range, [])
    else:
        meta_ads_raw = []
        
    meta_ads = []
    for ad in meta_ads_raw:
        meta_ads.append(dict(ad))
        
    for ad in meta_ads:
        ad_id = ad["id"]
        direct = direct_ads.get(ad_id, {"leads": 0, "approved": 0, "activated": 0})
        ad["dinx_leads"] = direct["leads"]
        ad["dinx_approved"] = direct["approved"]
        ad["dinx_activated"] = direct["activated"]

    # Meta Spends split
    total_spend = sum(c["spend"] for c in meta_campaigns)
    
    # Classify campaigns: Lead Campaigns
    lead_campaign_spend = 0.0
    profile_visit_spend = 0.0
    
    for c in meta_campaigns:
        obj = c.get("objective", "").upper()
        c_name = c.get("name", "").lower()
        is_branding = "alcance" in c_name or "reconhecimento" in c_name or "engajamento" in c_name
        
        if not is_branding:
            lead_campaign_spend += c["spend"]
        else:
            profile_visit_spend += c["spend"]
            
    aggregated_data = {
        "last_updated": raw_data.get("last_updated"),
        "dinx_stats": {
            "total_leads": dinx_totals,
            "qualificados": qualificados_count,
            "qualificados_private": qualificados_private_count,
            "ativados": ativados_count,
            "status_breakdown": status_counts,
            "school_breakdown": school_counts,
            "income_breakdown": income_counts,
            "device_breakdown": device_counts,
            "origin_breakdown": origin_counts,
            "daily_trend": sorted_daily
        },
        "meta_stats": {
            "total_spend": total_spend,
            "lead_campaign_spend": lead_campaign_spend,
            "profile_visit_spend": profile_visit_spend,
            "campaigns": meta_campaigns,
            "adsets": meta_adsets,
            "ads": meta_ads
        },
        "ig_stats": {
            "profile": ig_profile,
            "media": ig_media
        }
    }
    
    return aggregated_data

def build_debug_data(exclude_internal=False, date_range="all", start_date=None, end_date=None):
    raw_data = load_raw_cache() or {}
    processed = get_processed_data(
        exclude_internal=exclude_internal,
        date_range=date_range,
        start_date=start_date,
        end_date=end_date
    )

    dinx_requests = raw_data.get("dinx_requests", [])
    meta_campaigns = processed.get("meta_stats", {}).get("campaigns", [])
    meta_adsets = processed.get("meta_stats", {}).get("adsets", [])
    meta_ads = processed.get("meta_stats", {}).get("ads", [])
    redis_mapping = raw_data.get("redis_mapping", {})
    form_leads_mapping = raw_data.get("form_leads_mapping", {})

    origin_counts = {}
    status_counts = {}
    school_counts = {}
    leads_with_email = 0
    leads_with_phone = 0
    leads_with_landing_url = 0
    leads_with_utm_campaign = 0
    active_private_leads = 0

    for lead in dinx_requests:
        origin = str(lead.get("origin"))
        status = str(lead.get("status"))
        school = str(lead.get("schoolType"))
        origin_counts[origin] = origin_counts.get(origin, 0) + 1
        status_counts[status] = status_counts.get(status, 0) + 1
        school_counts[school] = school_counts.get(school, 0) + 1

        if lead.get("email"):
            leads_with_email += 1
        if lead.get("phone"):
            leads_with_phone += 1
        if (
            lead.get("status") == "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED"
            and lead.get("schoolType") == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE"
        ):
            active_private_leads += 1
        landing_url = lead.get("landingUrl") or ""
        if landing_url:
            leads_with_landing_url += 1
            if "utm_campaign=" in landing_url:
                leads_with_utm_campaign += 1

    return {
        "last_updated": raw_data.get("last_updated"),
        "is_fetching": is_fetching,
        "request": {
            "exclude_internal": exclude_internal,
            "date_range": date_range,
            "start_date": start_date,
            "end_date": end_date
        },
        "raw_counts": {
            "dinx_requests": len(dinx_requests),
            "redis_mapping_keys": len(redis_mapping),
            "form_leads_mapping_keys": len(form_leads_mapping),
            "meta_form_ids": len(raw_data.get("meta_form_ids", [])),
            "meta_discovered_form_ids": len(raw_data.get("meta_discovered_form_ids", [])),
            "ig_media": len(raw_data.get("ig_media", [])),
            "meta_campaigns_by_range": {
                key: len(value) if isinstance(value, list) else 0
                for key, value in (raw_data.get("meta_campaigns", {}) or {}).items()
            },
            "meta_adsets_by_range": {
                key: len(value) if isinstance(value, list) else 0
                for key, value in (raw_data.get("meta_adsets", {}) or {}).items()
            },
            "meta_ads_by_range": {
                key: len(value) if isinstance(value, list) else 0
                for key, value in (raw_data.get("meta_ads", {}) or {}).items()
            }
        },
        "dinx_fields": {
            "origin_counts": origin_counts,
            "status_counts": status_counts,
            "school_counts": school_counts,
            "leads_with_email": leads_with_email,
            "leads_with_phone": leads_with_phone,
            "active_private_leads": active_private_leads,
            "leads_with_landing_url": leads_with_landing_url,
            "leads_with_utm_campaign": leads_with_utm_campaign
        },
        "meta_form_ids": raw_data.get("meta_form_ids", []),
        "meta_discovered_form_ids": raw_data.get("meta_discovered_form_ids", []),
        "processed_counts": {
            "dinx_total_leads": processed.get("dinx_stats", {}).get("total_leads", 0),
            "dinx_qualificados": processed.get("dinx_stats", {}).get("qualificados", 0),
            "dinx_qualificados_private": processed.get("dinx_stats", {}).get("qualificados_private", 0),
            "dinx_ativados": processed.get("dinx_stats", {}).get("ativados", 0),
            "meta_campaigns": len(meta_campaigns),
            "meta_adsets": len(meta_adsets),
            "meta_ads": len(meta_ads),
            "meta_leads_reported": sum(item.get("leads", 0) for item in meta_campaigns),
            "attributed_dinx_leads": sum(item.get("dinx_leads", 0) for item in meta_campaigns),
            "attributed_dinx_approved": sum(item.get("dinx_approved", 0) for item in meta_campaigns),
            "attributed_dinx_activated": sum(item.get("dinx_activated", 0) for item in meta_campaigns),
            "campaigns_with_meta_leads": sum(1 for item in meta_campaigns if item.get("leads", 0) > 0),
            "campaigns_with_attributed_approved": sum(1 for item in meta_campaigns if item.get("dinx_approved", 0) > 0)
        },
        "top_campaigns_by_meta_leads": sorted(
            [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "meta_leads": item.get("leads", 0),
                    "dinx_leads": item.get("dinx_leads", 0),
                    "dinx_approved": item.get("dinx_approved", 0),
                    "spend": item.get("spend", 0)
                }
                for item in meta_campaigns
            ],
            key=lambda item: item["meta_leads"],
            reverse=True
        )[:10],
        "top_campaigns_by_attributed_approved": sorted(
            [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "meta_leads": item.get("leads", 0),
                    "dinx_leads": item.get("dinx_leads", 0),
                    "dinx_approved": item.get("dinx_approved", 0),
                    "spend": item.get("spend", 0)
                }
                for item in meta_campaigns
            ],
            key=lambda item: item["dinx_approved"],
            reverse=True
        )[:10]
    }

class DashboardAPIHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Serve static files from the "public" directory
        parsed_url = urllib.parse.urlparse(path)
        clean_path = parsed_url.path
        if clean_path == "/" or clean_path == "":
            clean_path = "/index.html"
            
        relative_path = clean_path.lstrip("/")
        return os.path.join(PUBLIC_DIR, relative_path)
        
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        exclude_internal = query_params.get("exclude_internal", ["false"])[0].lower() == "true"
        date_range = query_params.get("date_range", ["all"])[0].lower()
        start_date = query_params.get("start_date", [None])[0]
        end_date = query_params.get("end_date", [None])[0]

        if parsed_url.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                data = get_processed_data(exclude_internal=exclude_internal, date_range=date_range, start_date=start_date, end_date=end_date)
                response_payload = {
                    "status": "success",
                    "is_fetching": is_fetching,
                    "data": data
                }
                self.wfile.write(json.dumps(response_payload, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                import traceback
                error_payload = {"error": str(e), "traceback": traceback.format_exc()}
                self.wfile.write(json.dumps(error_payload, ensure_ascii=False).encode("utf-8"))
        elif parsed_url.path == "/api/debug-meta":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                # Puxa 1 lead recente pra gente ver exatamente o que a Meta entrega
                url = f"https://graph.facebook.com/{META_VERSION}/2230521901040318/leads?fields=id,campaign_id,adset_id,ad_id,field_data&limit=1&access_token={META_ACCESS_TOKEN}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        elif parsed_url.path == "/api/debug-data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                data = build_debug_data(
                    exclude_internal=exclude_internal,
                    date_range=date_range,
                    start_date=start_date,
                    end_date=end_date
                )
                self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
            except Exception as e:
                import traceback
                error_payload = {"error": str(e), "traceback": traceback.format_exc()}
                self.wfile.write(json.dumps(error_payload, ensure_ascii=False).encode("utf-8"))
        elif parsed_url.path == "/api/sync":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            # Start background sync
            start_background_fetch()
            
            try:
                data = get_processed_data(exclude_internal=exclude_internal, date_range=date_range, start_date=start_date, end_date=end_date)
                response_payload = {
                    "status": "syncing",
                    "is_fetching": True,
                    "data": data
                }
                self.wfile.write(json.dumps(response_payload, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                import traceback
                error_payload = {"error": str(e), "traceback": traceback.format_exc()}
                self.wfile.write(json.dumps(error_payload, ensure_ascii=False).encode("utf-8"))
        else:
            # Fallback to serving static files from public/
            super().do_GET()

# Create public dir if it does not exist
if not os.path.exists(PUBLIC_DIR):
    os.makedirs(PUBLIC_DIR)

if __name__ == "__main__":
    # Check if raw cache exists
    raw_data = load_raw_cache()
    if not raw_data:
        print("Initial cache initialization (triggering background)...")
        start_background_fetch()
        
    print(f"Starting server on http://localhost:{PORT} ...")
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer(("", PORT), DashboardAPIHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
