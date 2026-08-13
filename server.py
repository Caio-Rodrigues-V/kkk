import http.server
import socketserver
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import os
import sys

# Ensure UTF-8 console output
sys.stdout.reconfigure(encoding='utf-8')

PORT = int(os.environ.get("PORT", 8000))
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), "public")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache.json")
CACHE_EXPIRY_MINUTES = 15

# API Keys and tokens from user request
META_ACCESS_TOKEN = "EAAO4iW6Iza4BRZB9QAuxJbtOpMDZCPfvXPbKzlkAE0A2PL6UKEccwytf8OEnMhcM0Ak6HUzhxAsPd1sU5ze7nbvUd3U2Iu9hEYcBjZCqiz6YWxqs3Ow5O3TZBSAuazdnJPJuYzcZApk1swuqK2L8xv25ShwLxdTKKNCMHNH30IGNglpbjiahZCe9vDTedZC6ffA"
META_AD_ACCOUNT = "act_814077324704125"
META_IG_ACCOUNT = "17841470282486347"
META_VERSION = "v25.0"

DINX_API_KEY = "WjdYLb55nKAqabVHxMfdLWr3Sl2DCL8JCPeOHanwn2l9SapS9x"
DINX_LIST_URL = "https://bff.prd.dinx.app/site.beta_access.v1.SiteBetaAccessService/ListBetaAccess"

def fetch_live_data():
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
        with urllib.request.urlopen(req) as resp:
            dinx_res = json.loads(resp.read().decode("utf-8"))
            dinx_requests = dinx_res.get("requests", [])
            print(f"Fetched {len(dinx_requests)} leads from Dinx API.")
    except Exception as e:
        print("Error fetching Dinx data:", e)
        
    # 2. Fetch Meta Ads Campaigns and insights
    meta_campaigns = []
    meta_insights = []
    try:
        # Get campaigns metadata (status, effective_status)
        url_c = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/campaigns?fields=name,status,effective_status,objective&limit=100&access_token={META_ACCESS_TOKEN}"
        req_c = urllib.request.Request(url_c, headers={"User-Agent": "Mozilla/5.0"})
        campaigns_meta = {}
        with urllib.request.urlopen(req_c) as resp:
            campaigns_res = json.loads(resp.read().decode("utf-8"))
            for c in campaigns_res.get("data", []):
                campaigns_meta[c["id"]] = c
                
        # Get insights (spend, clicks, actions, cpc, ctr)
        url_i = f"https://graph.facebook.com/{META_VERSION}/{META_AD_ACCOUNT}/insights?level=campaign&fields=campaign_name,campaign_id,spend,impressions,clicks,actions,cpc,ctr&date_preset=maximum&limit=100&access_token={META_ACCESS_TOKEN}"
        req_i = urllib.request.Request(url_i, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_i) as resp:
            insights_res = json.loads(resp.read().decode("utf-8"))
            meta_insights = insights_res.get("data", [])
            
        # Merge them
        for item in meta_insights:
            c_id = item.get("campaign_id")
            meta_info = campaigns_meta.get(c_id, {})
            
            # Find lead count
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
        print(f"Fetched {len(meta_campaigns)} campaigns with insights from Meta Ads.")
    except Exception as e:
        print("Error fetching Meta Ads data:", e)
        if hasattr(e, "read"):
            try:
                print("Error body:", e.read().decode("utf-8"))
            except:
                pass

    # 3. Fetch Instagram profile & media
    ig_profile = {}
    ig_media = []
    try:
        # Profile
        url_p = f"https://graph.facebook.com/{META_VERSION}/{META_IG_ACCOUNT}?fields=username,name,profile_picture_url,followers_count,media_count,biography,website&access_token={META_ACCESS_TOKEN}"
        req_p = urllib.request.Request(url_p, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_p) as resp:
            ig_profile = json.loads(resp.read().decode("utf-8"))
            
        # Media posts
        url_m = f"https://graph.facebook.com/{META_VERSION}/{META_IG_ACCOUNT}/media?fields=id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count&limit=6&access_token={META_ACCESS_TOKEN}"
        req_m = urllib.request.Request(url_m, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_m) as resp:
            ig_media_res = json.loads(resp.read().decode("utf-8"))
            ig_media = ig_media_res.get("data", [])
        print("Fetched Instagram profile and recent media.")
    except Exception as e:
        print("Error fetching Instagram data:", e)
        
    # 4. Aggregations & Calculations
    
    # Dinx counters
    dinx_totals = len(dinx_requests)
    status_counts = {}
    school_counts = {}
    income_counts = {}
    device_counts = {}
    origin_counts = {}
    daily_registrations = {}
    
    qualificados_count = 0
    ativados_count = 0
    qualificados_private_count = 0
    
    for r in dinx_requests:
        status = r.get("status")
        school = r.get("schoolType")
        income = r.get("incomeRange")
        device = r.get("deviceType")
        origin = r.get("origin")
        created_at = r.get("createdAt")
        
        # Categorizations
        status_counts[status] = status_counts.get(status, 0) + 1
        school_counts[school] = school_counts.get(school, 0) + 1
        income_counts[income] = income_counts.get(income, 0) + 1
        device_counts[device] = device_counts.get(device, 0) + 1
        origin_counts[origin] = origin_counts.get(origin, 0) + 1
        
        is_qualificado = status in ["SITE_BETA_ACCESS_INVITE_STATUS_APPROVED", "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED"]
        is_ativado = (status == "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED") and (school == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE")
        
        if is_qualificado:
            qualificados_count += 1
            if school == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE":
                qualificados_private_count += 1
        if is_ativado:
            ativados_count += 1
            
        # Daily registrations, qualifications and activations trend (cohort-based)
        if created_at:
            day_str = created_at[:10]  # YYYY-MM-DD
            if day_str not in daily_registrations:
                daily_registrations[day_str] = {"cadastros": 0, "qualificados": 0, "ativados": 0}
            daily_registrations[day_str]["cadastros"] += 1
            if is_qualificado:
                daily_registrations[day_str]["qualificados"] += 1
            if is_ativado:
                daily_registrations[day_str]["ativados"] += 1
                
    # Sort daily registrations by date
    sorted_daily = []
    for day in sorted(daily_registrations.keys()):
        sorted_daily.append({
            "date": day,
            "cadastros": daily_registrations[day]["cadastros"],
            "qualificados": daily_registrations[day]["qualificados"],
            "ativados": daily_registrations[day]["ativados"]
        })
        
    # 5. Campaign Attribution Logic (Dinx Backoffice to Meta Campaigns)
    from urllib.parse import urlparse, parse_qs
    
    # Direct UTM campaign mapping: campaign_id -> { "leads": 0, "approved": 0, "activated": 0 }
    direct_attributions = {}
    unattributed_meta_leads = []
    
    for r in dinx_requests:
        status = r.get("status")
        is_qualificado = status in ["SITE_BETA_ACCESS_INVITE_STATUS_APPROVED", "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED"]
        is_qualificado = status in ["SITE_BETA_ACCESS_INVITE_STATUS_APPROVED", "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED"]
        is_ativado = (status == "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED") and (school == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE")
        
        attributed = False
        l_url = r.get("landingUrl")
        if l_url:
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
                        if is_ativado:
                            direct_attributions[camp_id]["activated"] += 1
                        attributed = True
            except:
                pass
                
        if not attributed and r.get("origin") == "SITE_BETA_ACCESS_INVITE_ORIGIN_META":
            unattributed_meta_leads.append(r)
            
    total_unattributed_leads = len(unattributed_meta_leads)
    total_unattributed_approved = len([r for r in unattributed_meta_leads if r.get("status") in ["SITE_BETA_ACCESS_INVITE_STATUS_APPROVED", "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED"]])
    total_unattributed_activated = len([r for r in unattributed_meta_leads if (r.get("status") == "SITE_BETA_ACCESS_INVITE_STATUS_USER_CREATED") and (r.get("schoolType") == "SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE")])
    
    total_meta_leads_reported = sum(c["leads"] for c in meta_campaigns)
    
    # Calculate float shares and base integer parts
    shares_leads = []
    shares_approved = []
    shares_activated = []
    
    for c in meta_campaigns:
        c_meta_leads = c["leads"]
        prop = (c_meta_leads / total_meta_leads_reported) if total_meta_leads_reported > 0 else 0.0
        
        shares_leads.append(prop * total_unattributed_leads)
        shares_approved.append(prop * total_unattributed_approved)
        shares_activated.append(prop * total_unattributed_activated)
        
    def distribute_largest_remainder(shares, total_target):
        if total_target <= 0:
            return [0] * len(shares)
        ints = [int(x) for x in shares]
        remainders = [(x - i, idx) for idx, (x, i) in enumerate(zip(shares, ints))]
        diff = total_target - sum(ints)
        # Sort by remainder descending
        remainders.sort(key=lambda item: item[0], reverse=True)
        for k in range(min(diff, len(shares))):
            idx = remainders[k][1]
            ints[idx] += 1
        return ints

    allocated_leads = distribute_largest_remainder(shares_leads, total_unattributed_leads)
    allocated_approved = distribute_largest_remainder(shares_approved, total_unattributed_approved)
    allocated_activated = distribute_largest_remainder(shares_activated, total_unattributed_activated)
    
    # Enrich campaign list with attributed backoffice data
    for idx, c in enumerate(meta_campaigns):
        c_id = c["id"]
        direct = direct_attributions.get(c_id, {"leads": 0, "approved": 0, "activated": 0})
        
        c["dinx_leads"] = direct["leads"] + allocated_leads[idx]
        c["dinx_approved"] = direct["approved"] + allocated_approved[idx]
        c["dinx_activated"] = direct["activated"] + allocated_activated[idx]

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
        "last_updated": datetime.now().isoformat(),
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
            "campaigns": meta_campaigns
        },
        "ig_stats": {
            "profile": ig_profile,
            "media": ig_media
        }
    }
    
    # Save cache to file
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(aggregated_data, f, ensure_ascii=False, indent=2)
        
    return aggregated_data

def get_cached_data(force=False):
    if not force and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Check expiry
            updated_time = datetime.fromisoformat(data["last_updated"])
            if datetime.now() - updated_time < timedelta(minutes=CACHE_EXPIRY_MINUTES):
                print(f"[{datetime.now().isoformat()}] Serving data from local cache (created {updated_time.isoformat()}).")
                return data
        except Exception as e:
            print("Error reading cache:", e)
            
    return fetch_live_data()

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
        if parsed_url.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = get_cached_data(force=False)
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        elif parsed_url.path == "/api/sync":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = get_cached_data(force=True)
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            # Fallback to serving static files from public/
            super().do_GET()

# Create public dir if it does not exist
if not os.path.exists(PUBLIC_DIR):
    os.makedirs(PUBLIC_DIR)

if __name__ == "__main__":
    # Perform initial fetch to verify connection and initialize cache
    try:
        get_cached_data()
    except Exception as e:
        print("Initial data fetch warning:", e)
        
    print(f"Starting server on http://localhost:{PORT} ...")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), DashboardAPIHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")
