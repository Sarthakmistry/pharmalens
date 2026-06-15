import requests
import json
import time
from datetime import datetime, timedelta
from google.cloud import storage

SPONSORS = [
    "Novo Nordisk", "Eli Lilly", "Bristol-Myers Squibb", "Merck", "Pfizer",
    "Roche", "AstraZeneca", "Novartis", "Johnson & Johnson", "AbbVie",
    "Amgen", "Gilead", "Biogen", "Regeneron", "Vertex",
    "Sanofi", "GSK", "Takeda", "Eisai", "Bayer"
]

# Maps display name → folder slug
SLUG_MAP = {
    "Novo Nordisk": "novo-nordisk",
    "Eli Lilly": "eli-lilly",
    "Bristol-Myers Squibb": "bristol-myers-squibb",
    "Merck": "merck",
    "Pfizer": "pfizer",
    "Roche": "roche",
    "AstraZeneca": "astrazeneca",
    "Novartis": "novartis",
    "Johnson & Johnson": "johnson-and-johnson",
    "AbbVie": "abbvie",
    "Amgen": "amgen",
    "Gilead": "gilead",
    "Biogen": "biogen",
    "Regeneron": "regeneron",
    "Vertex": "vertex",
    "Sanofi": "sanofi",
    "GSK": "gsk",
    "Takeda": "takeda",
    "Bayer": "bayer"
}

TARGET_FIELDS = (
    "NCTId,BriefTitle,OverallStatus,Phase,StudyType,"
    "StartDate,PrimaryCompletionDate,CompletionDate,LastUpdatePostDate,"
    "LeadSponsorName,LeadSponsorClass,CollaboratorName,CollaboratorClass,"
    "Condition,BriefSummary,EnrollmentCount,EnrollmentType,"
    "InterventionType,InterventionName,PrimaryOutcomeMeasure,"
    "PrimaryOutcomeTimeFrame,HasResults"
)

# Phase filter — only 2, 3, 4 per project spec
PHASE_FILTER = "AREA[Phase]PHASE2 OR AREA[Phase]PHASE3 OR AREA[Phase]PHASE4"

# Status filter — only recruiting, active, completed, terminated
STATUS_FILTER = (
    "AREA[OverallStatus]RECRUITING OR "
    "AREA[OverallStatus]ACTIVE_NOT_RECRUITING OR "
    "AREA[OverallStatus]COMPLETED OR "
    "AREA[OverallStatus]TERMINATED"
)


def parse_trial_data(study):
    protocol = study.get("protocolSection", {})
    id_mod = protocol.get("identificationModule", {})
    status_mod = protocol.get("statusModule", {})
    design_mod = protocol.get("designModule", {})
    sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
    cond_mod = protocol.get("conditionsModule", {})
    desc_mod = protocol.get("descriptionModule", {})
    interv_mod = protocol.get("armsInterventionsModule", {})
    outcome_mod = protocol.get("outcomesModule", {})

    def extract_list(item_list, key):
        return " | ".join([str(i.get(key, "")) for i in item_list]) if item_list else ""

    return {
        "NCTId": id_mod.get("nctId", ""),
        "BriefTitle": id_mod.get("briefTitle", ""),
        "OverallStatus": status_mod.get("overallStatus", ""),
        "Phase": " | ".join(design_mod.get("phases", [])),
        "StudyType": design_mod.get("studyType", ""),
        "StartDate": status_mod.get("startDateStruct", {}).get("date", ""),
        "PrimaryCompletionDate": status_mod.get("primaryCompletionDateStruct", {}).get("date", ""),
        "CompletionDate": status_mod.get("completionDateStruct", {}).get("date", ""),
        "LastUpdatePostDate": status_mod.get("lastUpdatePostDateStruct", {}).get("date", ""),
        "LeadSponsorName": sponsor_mod.get("leadSponsor", {}).get("name", ""),
        "LeadSponsorClass": sponsor_mod.get("leadSponsor", {}).get("class", ""),
        "CollaboratorName": extract_list(sponsor_mod.get("collaborators", []), "name"),
        "CollaboratorClass": extract_list(sponsor_mod.get("collaborators", []), "class"),
        "Condition": " | ".join(cond_mod.get("conditions", [])),
        "BriefSummary": desc_mod.get("briefSummary", "").replace("\n", " "),
        "EnrollmentCount": design_mod.get("enrollmentInfo", {}).get("count", ""),
        "EnrollmentType": design_mod.get("enrollmentInfo", {}).get("type", ""),
        "InterventionType": extract_list(interv_mod.get("interventions", []), "type"),
        "InterventionName": extract_list(interv_mod.get("interventions", []), "name"),
        "PrimaryOutcomeMeasure": extract_list(outcome_mod.get("primaryOutcomes", []), "measure"),
        "PrimaryOutcomeTimeFrame": extract_list(outcome_mod.get("primaryOutcomes", []), "timeFrame"),
        "HasResults": study.get("hasResults", False)
    }


def upload_trial_to_gcs(client, bucket_name, company_slug, date_str, trial):
    """Uploads one trial as its own JSON file: raw/ctgov/{slug}/{date}/NCT{id}.json"""
    nct_id = trial.get("NCTId", "UNKNOWN")
    blob_path = f"raw/ctgov/{company_slug}/{date_str}/{nct_id}.json"
    
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    
    # Skip if already exists (append-only rule)
    if blob.exists():
        print(f"    [skip] {blob_path} already exists")
        return
    
    blob.upload_from_string(
        json.dumps(trial, indent=2),
        content_type="application/json"
    )
    print(f"    [ok] gs://{bucket_name}/{blob_path}")


def fetch_trials_for_sponsor(sponsor, date_filter):
    """Fetches all matching trials for one sponsor from CT.gov API."""
    base_url = "https://clinicaltrials.gov/api/v2/studies"
    trials = []
    
    params = {
        "query.spons": sponsor,
        "query.term": f"({PHASE_FILTER}) AND ({STATUS_FILTER}) AND ({date_filter})",
        "fields": TARGET_FIELDS,
        "format": "json",
        "pageSize": 1000
    }
    
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        try:
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            for study in data.get("studies", []):
                parsed = parse_trial_data(study)
                # Enforce lead sponsor match
                if sponsor.lower() in parsed["LeadSponsorName"].lower():
                    trials.append(parsed)
            
            page_token = data.get("nextPageToken")
            if not page_token:
                break
                
        except requests.exceptions.RequestException as e:
            print(f"  [!] Error fetching {sponsor}: {e}")
            break
        
        time.sleep(0.5)
    
    return trials

def fetch_trial_results(nct_id):
    """Fetches resultsSection for a single trial that has posted results."""
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"
    params = {"fields": "resultsSection"}
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("resultsSection", {})
    except requests.exceptions.RequestException as e:
        print(f"  [!] Error fetching results for {nct_id}: {e}")
        return {}

def main():
    import os
    GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "pharmalens-raw")
    
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    # For initial seed: 5-year lookback
    # For daily delta: last 30 days
    seed_mode = os.environ.get("SEED_MODE", "false").lower() == "true"
    
    if seed_mode:
        one_year_ago = (now - timedelta(days=365*1)).strftime("%Y-%m-%d")
        date_filter = f"AREA[LastUpdatePostDate]RANGE[{one_year_ago},{today_str}]"
        print(f"SEED MODE — pulling 1-year lookback from {one_year_ago}")
    else:
        last_month = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        date_filter = f"AREA[LastUpdatePostDate]RANGE[{last_month},{today_str}]"
        print(f"DELTA MODE — pulling updates since {last_month}")
    
    gcs_client = storage.Client()
    total_uploaded = 0
    
    for sponsor in SPONSORS:
        slug = SLUG_MAP[sponsor]
        print(f"\n→ {sponsor} ({slug})")
        
        trials = fetch_trials_for_sponsor(sponsor, date_filter)
        print(f"  Found {len(trials)} trials")
        
        for trial in trials:
            # Fetch and attach results if available
            if trial.get("HasResults"):
                results = fetch_trial_results(trial["NCTId"])
                if results:
                    trial["resultsSection"] = results
                time.sleep(0.3)  # be polite to the API
            
            upload_trial_to_gcs(gcs_client, GCS_BUCKET_NAME, slug, today_str, trial)
            total_uploaded += 1
        
        time.sleep(0.5)
    
    print(f"\nDone. {total_uploaded} files deposited to gs://{GCS_BUCKET_NAME}/raw/ctgov/ (monthly run)")


if __name__ == "__main__":
    main()