from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
from unified_automator import DABClient, settings
import os
import tempfile
import shutil
import uuid
import time
import zipfile
import threading
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

# Setup Debug Logging
logging.basicConfig(filename='bulk_debug.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# Ensure download dir exists
settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Use system temp dir to avoid triggering Flask reloader on file creation
# Use system temp dir to avoid triggering Flask reloader on file creation
TEMP_DIR = Path(tempfile.gettempdir()) / "music_web_bulk"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Global Client (Only for single search/download speed enhancement)
# For bulk, we will use fresh clients to avoid concurrency issues with curl_cffi sessions
GLOBAL_CLIENT = None
CLIENT_LOCK = threading.Lock()

# Job Store
JOBS = {}
JOB_LOCK = threading.Lock()

def get_global_client():
    global GLOBAL_CLIENT
    with CLIENT_LOCK:
        if GLOBAL_CLIENT is None:
            try:
                GLOBAL_CLIENT = DABClient()
                GLOBAL_CLIENT.login()
            except Exception as e:
                logging.error(f"Global login failed: {e}")
                raise
        return GLOBAL_CLIENT

def create_fresh_client():
    client = DABClient()
    client.login()
    return client

def cleanup_file(path):
    try:
        if path.exists(): os.remove(path)
    except Exception as e:
        logging.error(f"Cleanup failed for {path}: {e}")

# Improve regex import
import re
import json
import base64

def scrape_spotify_playlist(url):
    try:
        # Convert to embed URL for easier scraping
        if '/embed/' not in url:
            url = url.replace('open.spotify.com/playlist/', 'open.spotify.com/embed/playlist/')
            
        logging.info(f"Scraping Spotify URL: {url}")
        response = cffi_requests.get(url, impersonate="chrome120")
        if response.status_code != 200:
            logging.error(f"Spotify scrape failed status: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.content, 'html.parser')
        tracks = []
        
        # Method: Parse __NEXT_DATA__
        next_data = soup.find('script', id='__NEXT_DATA__')
        if next_data:
            try:
                data = json.loads(next_data.string)
                entity = data['props']['pageProps']['state']['data']['entity']
                if 'trackList' in entity:
                    for t in entity['trackList']:
                        title = t.get('title')
                        artist = t.get('subtitle') # In embed view, subtitle is the artist
                        if title and artist:
                            # Clean up HTML entities or weird chars if needed?
                            # Usually simple text.
                            tracks.append(f"{artist} - {title}")
                    
                    logging.info(f"Found {len(tracks)} tracks in __NEXT_DATA__")
                    return tracks
            except Exception as e:
                logging.error(f"Error parsing NEXT_DATA: {e}")

        logging.warning("JSON scrape failed, trying legacy HTML selector...")
        # Fallback (unlikely needed for embed but good to have)
        return []

    except Exception as e:
        logging.error(f"Scrape error: {e}")
        return []

def background_bulk_download(job_id, track_list, job_dir):
    try:
        logging.info(f"Starting job {job_id} with {len(track_list)} tracks")
        
        successful_downloads = []
        
        with JOB_LOCK:
            JOBS[job_id]['total'] = len(track_list)
            
        def process_song(query):
            # Create a defined local independent client for this thread
            # This prevents session state leaking or race conditions
            local_client = None
            try:
                local_client = create_fresh_client()
                
                logging.info(f"Searching for: {query}")
                results = local_client.search(query)
                if not results:
                    logging.warning(f"No results for: {query}")
                    return None
                
                track = results[0]
                tid = track['id']
                # Safe metadata extraction
                artist = track['artist']['name'] if isinstance(track.get('artist'), dict) else str(track.get('artist', 'Unknown'))
                title = track.get('title', 'Unknown')
                
                # Fix: API returns flat albumTitle and albumCover
                album = track.get('albumTitle') or (track['album']['name'] if isinstance(track.get('album'), dict) else str(track.get('album', 'Unknown')))
                
                cover_url = track.get('albumCover')
                if not cover_url and isinstance(track.get('album'), dict):
                    cover_url = track['album'].get('cover_xl') or track['album'].get('cover')

                # Extract Year and Genre
                year = track.get('releaseDate', '')[:4] if track.get('releaseDate') else ''
                genre = track.get('genre', '')

                metadata = {
                    'artist': artist,
                    'title': title,
                    'album': album,
                    'cover_url': cover_url,
                    'date': year,
                    'genre': genre
                }
                
                logging.info(f"Downloading: {artist} - {title}")
                fpath = local_client.download_track(tid, metadata)
                
                if fpath and fpath.exists():
                    # Move to job directory immediately to avoid conflicts
                    # Ensure unique filename in job dir
                    safe_name = f"{uuid.uuid4().hex}_{fpath.name}"
                    dest = job_dir / safe_name
                    shutil.move(fpath, dest)
                    # Return tuple: (path_on_disk, desired_name_in_zip)
                    return (dest, fpath.name)
                else:
                    logging.error(f"Download returned None for {query}")
                    return None
                    
            except Exception as e:
                logging.error(f"Error processing {query}: {e}")
                return None
    
        # Parallel Execution
        # Reducing workers to 2 to see if stability improves, or keep 4 if robust
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(process_song, track): track for track in track_list}
            for future in futures:
                try:
                    res = future.result()
                    with JOB_LOCK:
                        JOBS[job_id]['progress'] += 1
                    if res:
                        successful_downloads.append(res)
                except Exception as e:
                    logging.error(f"Thread worker failed: {e}")
                    
        logging.info(f"Job {job_id} finished logic. Success: {len(successful_downloads)}")

        # Wait 5 seconds as requested
        logging.info("Waiting 5 seconds before zipping...")
        time.sleep(5)
    
        # Zip It
        if successful_downloads:
            try:
                zip_path = TEMP_DIR / f"{job_id}.zip"
                with zipfile.ZipFile(zip_path, 'w') as zf:
                    for fpath, original_name in successful_downloads:
                        try:
                            zf.write(fpath, arcname=original_name)
                        except Exception as ez:
                            logging.error(f"Failed to zip {original_name}: {ez}")
                            
                        # Try to cleanup temp file
                        try: cleanup_file(fpath) 
                        except: pass
            except Exception as ez:
                logging.error(f"Zip creation critical failure: {ez}")
                zip_path = None
        else:
            zip_path = None
        
        # Cleanup Job Dir
        try:
            shutil.rmtree(job_dir)
        except Exception as e:
            logging.error(f"Failed to remove job dir: {e}")
    
        with JOB_LOCK:
            JOBS[job_id]['status'] = 'completed'
            JOBS[job_id]['zip_path'] = str(zip_path) if zip_path else None

    except Exception as e:
        logging.critical(f"CRITICAL JOB FAILURE {job_id}: {e}")
        with JOB_LOCK:
            JOBS[job_id]['status'] = 'error'
            JOBS[job_id]['error'] = str(e)

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/search')
def search():
    query = request.args.get('q')
    if not query: return jsonify({"error": "No query"}), 400
    try:
        client = get_global_client()
        results = client.search(query)
        return jsonify(results)
    except Exception as e:
        # Retry with fresh client if global failed (expired session?)
        try:
            global GLOBAL_CLIENT
            GLOBAL_CLIENT = None # Force reset
            client = get_global_client()
            results = client.search(query)
            return jsonify(results)
        except Exception as e2:
            return jsonify({"error": str(e2)}), 500

@app.route('/api/download', methods=['POST'])
def download():
    data = request.json
    try:
        client = get_global_client()
        fpath = client.download_track(data['trackId'], data['metadata'])
        if not fpath: raise Exception("Download failed")
        
        def generate():
            with open(fpath, 'rb') as f:
                yield from f
            cleanup_file(fpath)
            
        return Response(stream_with_context(generate()), 
                       headers={"Content-Disposition": f"attachment; filename={fpath.name}", "Content-Type": "audio/flac"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bulk_init', methods=['POST'])
def bulk_init():
    data = request.json
    raw_text = data.get('text', '')
    
    # Check if input is a URL
    if 'spotify.com' in raw_text:
        tracks = scrape_spotify_playlist(raw_text.strip())
        if not tracks:
             return jsonify({"error": "Failed to scrape Spotify playlist. Please check URL or paste song list manually."}), 400
    else:
        tracks = [line.strip() for line in raw_text.split('\n') if line.strip()]
    if not tracks:
        return jsonify({"error": "No tracks found"}), 400
        
    job_id = str(uuid.uuid4())
    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    with JOB_LOCK:
        JOBS[job_id] = {
            'status': 'processing',
            'progress': 0,
            'total': len(tracks),
            'zip_path': None
        }
    
    thread = threading.Thread(target=background_bulk_download, args=(job_id, tracks, job_dir))
    thread.start()
    
    return jsonify({"jobId": job_id})

@app.route('/api/bulk_progress/<job_id>')
def bulk_progress(job_id):
    with JOB_LOCK:
        job = JOBS.get(job_id)
    if not job: return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@app.route('/api/bulk_result/<job_id>')
def bulk_result(job_id):
    with JOB_LOCK:
        job = JOBS.get(job_id)
    if not job: return jsonify({"error": "Job not found"}), 404
    
    if job.get('status') == 'error':
        return jsonify({"error": "Job failed"}), 500
        
    if job['status'] != 'completed':
        return jsonify({"error": "Not ready"}), 400
        
    if not job['zip_path']:
        return jsonify({"error": "No files downloaded"}), 404
        
    return send_file(job['zip_path'], as_attachment=True, download_name="songs.zip")

if __name__ == '__main__':
    # host='0.0.0.0' allows external connections (Required for AWS/Ngrok)
    app.run(debug=True, port=5000, host='0.0.0.0', threaded=True)
