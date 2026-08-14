import http.server
import socketserver
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import os
import sys
import threading

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
            
        for key in conn.scan_iter("*"):
            try:
                val_str = conn.get(key)
                if val_str:
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
            except Exception as e:
                pass
        print(f"Loaded {len(mapping)} mappings from Redis.")
    except Exception as e:
        print("Error fetching from Redis:", e)
    return mapping

def fetch_meta_form_leads(form_id):
    leads_mapping = {}  # lead_id -> campaign_id
    try:
        url = f"https://graph.facebook.com/{META_VERSION}/{form_id}/leads?fields=id,campaign_id&limit=1000&access_token={META_ACCESS_TOKEN}"
        while url:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                for lead in res.get("data", []):
                    l_id = lead.get("id")
                    c_id = lead.get("campaign_id")
                    if l_id and c_id:
                        leads_mapping[l_id] = c_id
                paging = res.get("paging", {})
                url = paging.get("next")
        print(f"Fetched {len(leads_mapping)} leads from Meta Form {form_id}.")
    except Exception as e:
        print(f"Error fetching leads for form {form_id}:", e)
    return leads_mapping

META_LEAD_CAMPAIGN_CACHE = {}  # lead_id -> campaign_id

def get_campaign_for_lead(lead_id, form_leads_mapping):
    if lead_id in form_leads_mapping:
        return form_leads_mapping[lead_id]
    return None

# Cache for custom Meta API queries (to avoid hitting Meta API repeatedly for the same dates)
CUSTOM_META_CACHE = {}  # Key: "start_date:end_date", Value: (timestamp, campaigns_list)
CUSTOM_META_CACHE_EXPIRY = timedelta(minutes=15)

def fetch_meta_campaigns_metadata():
    campaigns_meta = {}
    try:
        url = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/campaigns?fields=name,status,effective_status,objective&limit=150&access_token={META_ACCESS_TOKEN}"
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
    try:
        url = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/adsets?fields=name,status,effective_status,campaign_id&limit=150&access_token={META_ACCESS_TOKEN}"
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
    try:
        url = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/ads?fields=name,status,effective_status,campaign_id,adset_id,creative{{id,thumbnail_url}}&limit=150&access_token={META_ACCESS_TOKEN}"
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
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=campaign&fields=campaign_name,campaign_id,spend,impressions,clicks,actions,cpc,ctr&time_range={time_range}&limit=100&access_token={META_ACCESS_TOKEN}"
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
    try:
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=campaign&fields=campaign_name,campaign_id,spend,impressions,clicks,actions,cpc,ctr&date_preset={preset}&limit=100&access_token={META_ACCESS_TOKEN}"
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
    try:
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=adset&fields=adset_id,spend,impressions,clicks,actions&date_preset={preset}&limit=150&access_token={META_ACCESS_TOKEN}"
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
    try:
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=ad&fields=ad_id,spend,impressions,clicks,actions&date_preset={preset}&limit=150&access_token={META_ACCESS_TOKEN}"
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
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=adset&fields=adset_id,spend,impressions,clicks,actions&time_range={time_range}&limit=150&access_token={META_ACCESS_TOKEN}"
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

def fetch_raw_live_data():
    print(f"[{datetime.now().isoformat()}] Fetching live data from Dinx and Meta APIs...")
    
    # 1. Fetch Dinx leads (all 16,000+ items)
    dinx_requests = []
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
    
    # Fetch metadata once
    campaigns_meta = fetch_meta_campaigns_metadata()
    adsets_meta = fetch_meta_adsets_metadata()
    ads_meta = fetch_meta_ads_metadata()
    
    presets_map = {
        "all": "maximum",
        "7days": "last_7d",
        "30days": "last_30d",
        "thismonth": "this_month",
        "lastmonth": "last_month"
    }
    for range_key, preset in presets_map.items():
        meta_campaigns_by_preset[range_key] = fetch_meta_campaigns(preset, campaigns_meta)
        meta_adsets_by_preset[range_key] = fetch_meta_adsets(preset, adsets_meta)
        meta_ads_by_preset[range_key] = fetch_meta_ads(preset, ads_meta)

    # 3. Fetch Instagram profile & media
    ig_profile = {}
    ig_media = []
    try:
        # Profile
        url_p = f"https://graph.facebook.com/{META_VERSION}/{META_IG_ACCOUNT}?fields=username,name,profile_picture_url,followers_count,media_count,biography,website&access_token={META_ACCESS_TOKEN}"
        req_p = urllib.request.Request(url_p, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_p, timeout=15.0) as resp:
            ig_profile = json.loads(resp.read().decode("utf-8"))
            
        # Media posts
        url_m = f"https://graph.facebook.com/{META_VERSION}/{META_IG_ACCOUNT}/media?fields=id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count&limit=6&access_token={META_ACCESS_TOKEN}"
        req_m = urllib.request.Request(url_m, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_m, timeout=15.0) as resp:
            ig_media_res = json.loads(resp.read().decode("utf-8"))
            ig_media = ig_media_res.get("data", [])
        print("Fetched Instagram profile and recent media.")
    except Exception as e:
        print("Error fetching Instagram data:", e)
        
    # 4. Fetch Redis mapping & Meta form leads mapping
    redis_mapping = fetch_redis_mapping()
    form_leads_mapping = fetch_meta_form_leads("2230521901040318")
        
    return {
        "last_updated": datetime.now().isoformat(),
        "dinx_requests": dinx_requests,
        "meta_campaigns": meta_campaigns_by_preset,
        "meta_adsets": meta_adsets_by_preset,
        "meta_ads": meta_ads_by_preset,
        "ig_profile": ig_profile,
        "ig_media": ig_media,
        "redis_mapping": redis_mapping,
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
    ig_profile = raw_data.get("ig_profile", {})
    ig_media = raw_data.get("ig_media", [])

    # Filter out internal emails if requested
    if exclude_internal:
        dinx_requests = [r for r in dinx_requests_raw if not is_internal_email(r.get("email"))]
    else:
        dinx_requests = list(dinx_requests_raw)

    # Calculate date range boundaries for Dinx leads
    start_bound, end_bound = get_date_range_bounds(date_range, start_date, end_date)

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
                
    # Sort and filter daily registrations by date
    sorted_daily = []
    for day in sorted(daily_registrations.keys()):
        if date_str_in_range(day, start_bound, end_bound):
            sorted_daily.append({
                "date": day,
                "cadastros": daily_registrations[day].get("cadastros", 0),
                "qualificados": daily_registrations[day].get("qualificados", 0),
                "ativados": daily_registrations[day].get("ativados", 0),
                "ativados_cohort": daily_registrations[day].get("ativados_cohort", 0)
            })
        
    # 5. Campaign Attribution Logic (Dinx Backoffice to Meta Campaigns)
    from urllib.parse import urlparse, parse_qs
    
    # Load Redis mapping (email/phone -> lead_id) from raw_data cache
    redis_mapping = raw_data.get("redis_mapping", {})
    
    # Load Meta form leads mapping (lead_id -> campaign_id) from raw_data cache
    form_leads_mapping = raw_data.get("form_leads_mapping", {})
    
    # Direct UTM campaign mapping: campaign_id -> { "leads": 0, "approved": 0, "activated": 0 }
    direct_attributions = {}
    
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
            
        attributed = False
        
        # 1. Try Redis mapping first
        lead_id = None
        if email:
            lead_id = redis_mapping.get(email.lower().strip())
        if not lead_id and phone:
            clean_phone = "".join(filter(str.isdigit, str(phone)))
            if len(clean_phone) >= 10:
                lead_id = redis_mapping.get(clean_phone[-11:])
                
        if lead_id:
            camp_id = get_campaign_for_lead(lead_id, form_leads_mapping)
            if camp_id:
                if camp_id not in direct_attributions:
                    direct_attributions[camp_id] = {"leads": 0, "approved": 0, "activated": 0}
                if in_creation_range:
                    direct_attributions[camp_id]["leads"] += 1
                    if is_qualificado:
                        direct_attributions[camp_id]["approved"] += 1
                if is_ativado and in_activation_range:
                    direct_attributions[camp_id]["activated"] += 1
                attributed = True
                
        # 2. Fallback to direct UTM campaign mapping
        if not attributed:
            l_url = r.get("landingUrl")
            if l_url and in_creation_range:
                try:
                    parsed = urlparse(l_url)
                    qs = parse_qs(parsed.query)
                    if "utm_campaign" in qs:
                        camp_id = qs["utm_campaign"][0]
                        if camp_id:
                            if camp_id not in direct_attributions:
                                direct_attributions[camp_id] = {"leads": 0, "approved": 0, "activated": 0}
                            direct_attributions[camp_id]["leads"] += 1
                            if is_qualificado:
                                direct_attributions[camp_id]["approved"] += 1
                            if is_ativado and in_activation_range:
                                direct_attributions[camp_id]["activated"] += 1
                            attributed = True
                except:
                    pass
                
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
        direct = direct_attributions.get(c_id, {"leads": 0, "approved": 0, "activated": 0})
        
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

    # Meta Spends split
    total_spend = sum(c["spend"] for c in meta_campaigns)
    
    # Classify campaigns: Lead Campaigns (leads > 0 or has "FORMS" in name)
    lead_campaign_spend = 0.0
    profile_visit_spend = 0.0
    
    for c in meta_campaigns:
        is_lead_camp = c["leads"] > 0 or "FORMS" in c["name"].upper() or "LEADS" in c["name"].upper()
        if is_lead_camp:
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
            data = get_processed_data(exclude_internal=exclude_internal, date_range=date_range, start_date=start_date, end_date=end_date)
            response_payload = {
                "status": "success",
                "is_fetching": is_fetching,
                "data": data
            }
            self.wfile.write(json.dumps(response_payload, ensure_ascii=False).encode("utf-8"))
        elif parsed_url.path == "/api/sync":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            # Start background sync
            start_background_fetch()
            
            data = get_processed_data(exclude_internal=exclude_internal, date_range=date_range, start_date=start_date, end_date=end_date)
            response_payload = {
                "status": "syncing",
                "is_fetching": True,
                "data": data
            }
            self.wfile.write(json.dumps(response_payload, ensure_ascii=False).encode("utf-8"))
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
