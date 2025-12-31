import logging
import sys
import uuid
from pathlib import Path

# Configure logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

# Mock Flask app context if needed, but we essentially want to test the logic
# internal to server.py.
# We will import the necessary functions from server.py
# Note: we need to ensure server.py can be imported without running app.run()
# (It has if __name__ == '__main__': app.run(...) so it's safe)

from server import background_bulk_download, scrape_spotify_playlist, JOBS, settings

if __name__ == "__main__":
    print("--- Starting Reproduction Script ---")
    
    # 1. Test Scraper
    url = "https://open.spotify.com/playlist/3EzLEpQbVE1L3sZL3TvsHy"
    print(f"Scraping {url}...")
    tracks = scrape_spotify_playlist(url)
    print(f"found {len(tracks)} tracks")
    if not tracks:
        print("Scraper failed!")
        sys.exit(1)
        
    # Limit to 2 for speed
    test_tracks = tracks # Use ALL tracks to hit the error 
    
    # 2. Test Bulk Download Logic
    job_id = "debug_test_job"
    job_dir = Path.cwd() / "temp_bulk" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Starting bulk job with {len(test_tracks)} tracks...")
    
    # Initialize JOBS entry as bulk_init would
    JOBS[job_id] = {
        'status': 'processing',
        'progress': 0,
        'total': len(test_tracks),
        'zip_path': None
    }
    
    # We call the background function SYNCHRONOUSLY here
    try:
        background_bulk_download(job_id, test_tracks, job_dir)
        
        job_status = JOBS.get(job_id)
        print(f"Job Status: {job_status}")
        
        if job_status and job_status.get('status') == 'error':
             print(f"JOB FAILED: {job_status.get('error')}")
        else:
             print("Job finished successfully (check for zip)")
             
    except Exception as e:
        print(f"CRITICAL EXCEPTION CAUGHT: {e}")
        import traceback
        traceback.print_exc()

    print("--- End of Reproduction Script ---")
