import os
import sys
import logging
import time
import requests
import httpx
import threading
import subprocess
import uuid
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Any
from dotenv import load_dotenv

# Try importing dropbox
try:
    import dropbox
    from dropbox.files import WriteMode, CommitInfo, UploadSessionCursor
except ImportError:
    dropbox = None

# Try importing mutagen
try:
    from mutagen.flac import FLAC, Picture
except ImportError:
    pass

# Try importing torrentool
try:
    from torrentool.api import Torrent
except ImportError:
    Torrent = None

# Try importing qbittorrent
try:
    import qbittorrentapi
except ImportError:
    qbittorrentapi = None

from curl_cffi import requests as cffi_requests

# =========================================================================================
# CONFIGURATION
# =========================================================================================
env_path = Path.cwd() / ".env"
loaded = load_dotenv(dotenv_path=env_path, override=True)

class Config:
    # DAB Config
    DAB_BASE_URL = "https://dabmusic.xyz"
    DAB_API_URL = f"{DAB_BASE_URL}/api"
    DAB_EMAIL = os.getenv("DAB_EMAIL") or os.getenv("DAB_USERNAME")
    DAB_PASSWORD = os.getenv("DAB_PASSWORD")
    DAB_TOKEN = os.getenv("DAB_TOKEN")
    
    # RD Config
    RD_API_TOKEN = os.getenv("RD_API_TOKEN")
    
    # Dropbox Config
    DROPBOX_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN", "")
    DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY", "")
    DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET", "")
    DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN", "")
    UPLOAD_CHUNK_SIZE = 64 * 1024 * 1024

    # Torrent Config
    ARIA2C_BINARY = os.getenv("ARIA2C_BINARY_PATH", "aria2c")
    TORRENT_OUTPUT_PATH = Path.cwd() / "torrents"
    
    # QBit Config
    QBIT_HOST = os.getenv("QBITTORRENT_HOST", "http://localhost:8080")
    QBIT_USER = os.getenv("QBITTORRENT_USER", "admin")
    QBIT_PASS = os.getenv("QBITTORRENT_PASS", "adminadmin")

    # System Config
    DOWNLOAD_DIR = Path.cwd() / "downloads"
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/1337.0.0.0 Safari/537.36"
    REQUEST_TIMEOUT = 30

settings = Config()

# =========================================================================================
# LOGGING SETUP
# =========================================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("unified_automator.log", encoding='utf-8')
    ]
)
logger = logging.getLogger("UnifiedAuto")

def check_config():
    missing = []
    if not (settings.DAB_TOKEN or (settings.DAB_EMAIL and settings.DAB_PASSWORD)):
        missing.append("DAB_EMAIL/PASSWORD or DAB_TOKEN")
    if not settings.RD_API_TOKEN:
        missing.append("RD_API_TOKEN")
    
    if missing:
        logger.error(f"Missing configuration: {', '.join(missing)}")
        sys.exit(1)

# =========================================================================================
# DAB MUSIC CLIENT
# =========================================================================================
class DABClient:
    def __init__(self):
        self.cookies = {}
        self.session = cffi_requests.Session(impersonate="chrome124")
        self.session.headers.update({
            "Referer": f"{settings.DAB_BASE_URL}/",
            "Origin": settings.DAB_BASE_URL,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": settings.USER_AGENT,
        })

    def login(self) -> Dict:
        manual_chk = os.getenv("DAB_COOKIE_STRING")
        if manual_chk:
            logger.info("Using manual DAB_COOKIE_STRING from .env...")
            for cookie in manual_chk.split(';'):
                if '=' in cookie:
                    k, v = cookie.strip().split('=', 1)
                    self.cookies[k] = v
            self.session.cookies.update(self.cookies)
            return self.cookies

        if settings.DAB_TOKEN and isinstance(settings.DAB_TOKEN, dict):
             self.session.cookies.update(settings.DAB_TOKEN)
             return settings.DAB_TOKEN

        logger.info(f"Logging in to DAB as {settings.DAB_EMAIL}...")
        url = f"{settings.DAB_API_URL}/auth/login"
        payload = {"email": settings.DAB_EMAIL, "password": settings.DAB_PASSWORD}

        try:
            response = self.session.post(url, json=payload)
            if response.status_code == 200:
                self.cookies = dict(response.cookies)
                if not self.cookies: self.cookies = dict(self.session.cookies)
                if not self.cookies: raise Exception("Login successful but no cookies received.")
                logger.info("DAB Login successful.")
                return self.cookies
            elif response.status_code == 401: raise Exception("Invalid credentials.")
            elif response.status_code == 403: raise Exception("Cloudflare blocked the login request (403).")
            else: raise Exception(f"Login failed: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"DAB Login Error: {e}")
            raise

    def search(self, query: str) -> List[Dict]:
        url = f"{settings.DAB_API_URL}/search"
        params = {"q": query, "type": "track", "limit": 5}
        try:
            response = self.session.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get("tracks", data.get("data", data.get("results", [])))
            elif response.status_code == 401: raise Exception("DAB Token expired.")
            else: raise Exception(f"Search failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Search Error: {e}")
            return []

    def download_track(self, track_id: str, metadata: Dict) -> Optional[Path]:
        stream_url_endpoint = f"{settings.DAB_API_URL}/stream"
        params = {"trackId": track_id}
        try:
            resp = self.session.get(stream_url_endpoint, params=params)
            if resp.status_code != 200: raise Exception(f"Failed to get stream URL: {resp.status_code}")
            
            download_url = resp.json().get("url")
            if not download_url: raise Exception("No download URL in response.")

            def sanitize(n): return "".join(c for c in n if c.isalnum() or c in (' ', '-', '_')).strip()
            artist = sanitize(metadata.get('artist', 'Unknown'))
            title = sanitize(metadata.get('title', f'track_{track_id}'))
            filename = f"{artist} - {title}.flac"
            
            settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            file_path = settings.DOWNLOAD_DIR / filename
            
            logger.info(f"Downloading: {filename}")
            resp = self.session.get(download_url, stream=True)
            if resp.status_code != 200: raise Exception(f"Stream download failed: {resp.status_code}")
            
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk: f.write(chunk)
            
            self._tag_file(file_path, metadata)
            return file_path
        except Exception as e:
            logger.error(f"Download Error for {track_id}: {e}")
            return None

    def _tag_file(self, file_path: Path, metadata: Dict):
        try:
            if 'mutagen' not in sys.modules: return
            audio = FLAC(file_path)
            audio['title'] = metadata.get('title', 'Unknown')
            audio['artist'] = metadata.get('artist', 'Unknown')
            audio['album'] = metadata.get('album', 'Unknown')
            if metadata.get('date'): audio['date'] = metadata['date']
            if metadata.get('genre'): audio['genre'] = metadata['genre']
            cover_url = metadata.get('cover_url')
            if cover_url:
                try:
                    r = self.session.get(cover_url, timeout=10)
                    if r.status_code == 200:
                        pic = Picture()
                        pic.type = 3
                        pic.mime = "image/png" if r.content.startswith(b'\x89PNG') else "image/jpeg"
                        pic.desc = "Cover"
                        pic.data = r.content
                        audio.add_picture(pic)
                except Exception: pass
            audio.save()
        except Exception as e:
            logger.warning(f"Tagging failed: {e}")

# =========================================================================================
# SEEDERS
# =========================================================================================
def create_torrent(source_path: Path, trackers: List[str] = []) -> Path:
    if not Torrent: raise ImportError("torrentool not installed")
    settings.TORRENT_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    torrent_name = source_path.name
    torrent_file_path = settings.TORRENT_OUTPUT_PATH / f"{torrent_name}.torrent"
    t = Torrent.create_from(str(source_path))
    if trackers:
        t.announce_urls = trackers
    t.to_file(str(torrent_file_path))
    return torrent_file_path

class AriaSeeder:
    def __init__(self):
        self.processes = {}
        
    def start_seeding(self, torrent_path: Path, source_path: Path) -> str:
        if not torrent_path.exists(): return None
        seed_id = str(uuid.uuid4())
        save_dir = source_path.parent
        cmd = [
            settings.ARIA2C_BINARY, "--enable-dht=true", "--seed-ratio=0.0", "--seed-time=0",
            "--file-allocation=none", "--check-integrity=false", f"--dir={save_dir}", str(torrent_path)
        ]
        try:
             with open("aria2c_debug.log", "a") as log_file:
                process = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True)
                self.processes[seed_id] = process
                logger.info(f"Aria2c started (ID: {seed_id})")
                return seed_id
        except Exception as e:
            logger.error(f"Failed to start aria2c: {e}")
            return None

    def stop_seeding(self, seed_id: str):
        if seed_id in self.processes:
            p = self.processes[seed_id]
            p.terminate()
            try: p.wait(timeout=5)
            except: p.kill()
            del self.processes[seed_id]

# =========================================================================================
# QBITTORRENT SEEDER
# =========================================================================================
class QBitSeeder:
    def __init__(self):
        # self.client is no longer used as clients are instantiated per operation
        pass

    def start_seeding(self, torrent_path: Path, source_file: Path) -> str:
        if not qbittorrentapi:
            logger.error("qbittorrent-api not installed.")
            return None
        # Create a fresh client connection per thread if needed, or rely on shared if thread-safe
        # ideally we use one shared client but qbittorrent-api is sync. 
        # Using a fresh connection here just to be safe in threads
        try:
            local_client = qbittorrentapi.Client(host=settings.QBIT_HOST, username=settings.QBIT_USER, password=settings.QBIT_PASS)
            local_client.auth_log_in()
        except Exception as e:
            logger.error(f"Failed to connect to qBittorrent for start_seeding: {e}")
            return None
        
        save_path = source_file.parent.absolute()
        try:
            with open(torrent_path, "rb") as f:
                file_content = f.read()
            
            # Fix: Pass raw bytes for maximum compatibility (remote or local)
            local_client.torrents_add(torrent_files=file_content, save_path=str(save_path), is_paused=False, category="rd_automator")
            
            # Use torrentool to get hash instead of manual bencode
            t = Torrent.from_file(str(torrent_path))
            info_hash = t.info_hash
            
            # Initial Recheck/Announce
            local_client.torrents_recheck(torrent_hashes=info_hash)
            local_client.torrents_reannounce(torrent_hashes=info_hash)
            return info_hash
        except Exception as e:
            logger.error(f"qBittorrent Add Error: {e}")
            return None

    def force_announce(self, info_hash: str):
        if not qbittorrentapi: return
        try:
             # Just instantiate a quick client or use shared if robust
             # Since this is called in loop, let's try to reuse or lightweight
             local_client = qbittorrentapi.Client(host=settings.QBIT_HOST, username=settings.QBIT_USER, password=settings.QBIT_PASS)
             local_client.auth_log_in()
             local_client.torrents_reannounce(torrent_hashes=info_hash)
        except Exception:
            pass

    def stop_seeding(self, info_hash: str):
        if not qbittorrentapi: return
        try:
            local_client = qbittorrentapi.Client(host=settings.QBIT_HOST, username=settings.QBIT_USER, password=settings.QBIT_PASS)
            local_client.auth_log_in()
            local_client.torrents_delete(torrent_hashes=info_hash, delete_files=False)
        except Exception: pass

# =========================================================================================
# DROPBOX & RD IMPLEM
# =========================================================================================
class DropboxUploader:
    @staticmethod
    def _get_client():
        if not dropbox: return None
        if settings.DROPBOX_REFRESH_TOKEN and settings.DROPBOX_APP_KEY:
            return dropbox.Dropbox(app_key=settings.DROPBOX_APP_KEY, app_secret=settings.DROPBOX_APP_SECRET, oauth2_refresh_token=settings.DROPBOX_REFRESH_TOKEN)
        return dropbox.Dropbox(settings.DROPBOX_TOKEN)

    @staticmethod
    def upload_file(file_path: Path) -> Optional[str]:
        if not file_path.exists(): return None
        dbx = DropboxUploader._get_client()
        if not dbx: return None
        destination_path = "/" + file_path.name
        logger.info(f"Uploading {file_path.name} to Dropbox...")
        try:
            with open(file_path, "rb") as f:
                dbx.files_upload(f.read(), destination_path, mode=WriteMode('overwrite'))
            try:
                links = dbx.sharing_list_shared_links(path=destination_path, direct_only=True).links
                return links[0].url if links else dbx.sharing_create_shared_link_with_settings(destination_path).url
            except dropbox.exceptions.ApiError: return None
        except Exception as e:
            logger.error(f"Dropbox Upload Error: {e}")
            return None

    @staticmethod
    def delete_file(filename: str):
        dbx = DropboxUploader._get_client()
        if dbx: 
            try: dbx.files_delete_v2("/" + filename)
            except: pass

class RealDebridClient:
    BASE_URL = "https://api.real-debrid.com/rest/1.0"
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}
    def unrestrict_link(self, link: str) -> Optional[str]:
        try:
            resp = cffi_requests.post(f"{self.BASE_URL}/unrestrict/link", data={"link": link}, headers=self.headers)
            resp.raise_for_status()
            return resp.json().get("download")
        except Exception as e:
            logger.error(f"RD Unrestrict Error: {e}"); return None
    def upload_torrent(self, file_path: Path) -> str:
        with open(file_path, "rb") as f:
            file_content = f.read()
            # Fix: Pass raw bytes to curl_cffi put request
            resp = cffi_requests.put(f"{self.BASE_URL}/torrents/addTorrent", data=file_content, headers=self.headers)
            resp.raise_for_status(); data = resp.json()
            if "id" not in data: raise ValueError("No ID returned")
            return data["id"]
    def select_files(self, torrent_id: str):
        cffi_requests.post(f"{self.BASE_URL}/torrents/selectFiles/{torrent_id}", data={"files": "all"}, headers=self.headers)
    def get_torrent_info(self, torrent_id: str) -> Dict:
        return cffi_requests.get(f"{self.BASE_URL}/torrents/info/{torrent_id}", headers=self.headers).json()

# =========================================================================================
# MAIN ORCHESTRATOR
# =========================================================================================
def process_single_song(song_query: str, mode: str):
    # Instantiate OWN clients per thread to avoid race conditions with sessions/cookies
    dab = DABClient()
    rd = RealDebridClient(settings.RD_API_TOKEN)
    
    # Authenticate independent session
    try:
        dab.login()
    except Exception as e:
        logger.error(f"[{song_query}] Login failed: {e}")
        return

    logger.info(f"Processing: {song_query}")
    
    try:
        results = dab.search(song_query)
        if not results:
            logger.warning(f"No results for: {song_query}")
            return

        first_track = results[0]
        tid = first_track.get('id')
        artist = first_track.get('artist', {}).get('name', 'Unknown') if isinstance(first_track.get('artist'), dict) else str(first_track.get('artist', {}))
        title = first_track.get('title', 'Unknown')
        
        cover_url = None
        if isinstance(first_track.get('album'), dict):
            cover_url = first_track['album'].get('cover_xl') or first_track['album'].get('cover')

        metadata = {'artist': artist, 'album': str(first_track.get('album', {}).get('name', 'Unknown')), 'title': title, 'cover_url': cover_url}
        local_file = dab.download_track(tid, metadata)
        if not local_file: return
        
        final_link = None
        
        if mode == "dropbox":
            dbx_link = DropboxUploader.upload_file(local_file)
            if dbx_link:
                final_link = rd.unrestrict_link(dbx_link)
                DropboxUploader.delete_file(local_file.name)
        
        elif mode.startswith("torrent"):
            try:
                # Updated trackers list from ngosang/trackerslist
                trackers = [
                    "udp://tracker.opentrackr.org:1337/announce",
                    "udp://open.demonoid.ch:6969/announce",
                    "udp://open.demonii.com:1337/announce",
                    "udp://open.stealth.si:80/announce",
                    "udp://tracker.openbittorrent.com:80/announce",
                    "udp://tracker.torrent.eu.org:451/announce",
                    "udp://tracker2.dler.org:80/announce",
                    "udp://tracker.tryhackx.org:6969/announce",
                    "udp://tracker.theoks.net:6969/announce",
                    "udp://tracker.qu.ax:6969/announce",
                    "udp://tracker.gmi.gd:6969/announce",
                    "udp://tracker.fnix.net:6969/announce",
                    "udp://tracker.dler.org:6969/announce",
                    "udp://tracker.bittor.pw:1337/announce",
                    "udp://tracker.0x7c0.com:6969/announce",
                    "udp://tr4ck3r.duckdns.org:6969/announce",
                    "udp://t.overflow.biz:6969/announce",
                    "udp://run.publictracker.xyz:6969/announce",
                    "udp://retracker01-msk-virt.corbina.net:80/announce",
                    "udp://retracker.lanta.me:2710/announce",
                    "udp://p4p.arenabg.com:1337/announce"
                ]
                
                torrent_path = create_torrent(local_file, trackers=trackers)
                logger.info(f"[{song_query}] Created torrent: {torrent_path.name}")
                
                # UPLOAD TO RD FIRST
                torrent_id = rd.upload_torrent(torrent_path)
                logger.info(f"[{song_query}] Uploaded to RD. ID: {torrent_id}")
                rd.select_files(torrent_id)
                
                # START SEEDING
                seeder = None
                if mode == "torrent_aria":
                    seeder = AriaSeeder()
                elif mode == "torrent_qbit":
                    seeder = QBitSeeder() # Local instance
                
                if not seeder:
                    logger.error(f"[{song_query}] Seeder not initialized.")
                    return

                logger.info(f"[{song_query}] Starting local seeder...")
                seed_id = seeder.start_seeding(torrent_path, local_file) # Returns info_hash in QBit mode
                
                if not seed_id: 
                    logger.error(f"[{song_query}] Seeding failed.")
                    # Attempt to cleanup RD torrent if verify failed?
                    # rd.delete(torrent_id)
                    return
                
                # Initial state: We assume we must clean up if we didn't start seeding or if not torrent mode
                should_cleanup = True
                if mode.startswith("torrent"):
                     # If we are in torrent mode and started seeding, we default to NOT cleaning up unless success
                     should_cleanup = False
                
                # Check Loop with CONTINUOUS RE-ANNOUNCE
                max_retries = 30 # 2 minutes (4s interval)
                counter = 0
                while counter < max_retries:
                    info = rd.get_torrent_info(torrent_id)
                    status = info.get("status")
                    progress = info.get("progress", 0)
                    
                    if status == "downloaded":
                        links = info.get("links", [])
                        if links: final_link = links[0]
                        logger.info(f"[{song_query}] RD Download Complete.")
                        # SUCCESS: Now we can cleanup
                        should_cleanup = True
                        seeder.stop_seeding(seed_id)
                        break
                    
                    if status == "error" or status == "dead":
                         logger.error(f"[{song_query}] RD Torrent failed (dead).")
                         break
                    
                    # If still 0% or waiting_files, Spam Re-announce
                    if progress == 0 and mode == "torrent_qbit": # Only QBitSeeder has force_announce
                        # logger.debug(f"[{song_query}] Force re-announcing...")
                        seeder.force_announce(seed_id)
                    
                    time.sleep(4)
                    counter += 1
                
                if not final_link:
                    logger.warning(f"[{song_query}] RD did not finish. Leaving torrent seeding and local file on disk.")

            except Exception as e:
                logger.error(f"[{song_query}] Torrent mode error: {e}")

        if final_link:
            logger.info(f"SUCCESS! {artist} - {title} : {final_link}")
            with threading.Lock(): # Use a lock for thread-safe file writing
                 with open("unrestricted_links.txt", "a", encoding="utf-8") as out:
                    out.write(f"{artist} - {title} : {final_link}\n")
        
        # Cleanup Logic
        if should_cleanup:
            try: os.remove(local_file) 
            except: pass

    except Exception as e:
        logger.error(f"Error processing {song_query}: {e}")

def process_batch(file_path: str):
    check_config()
    print("\nSelect Upload Mode:")
    print("1. Torrent (Aria2c) - Lightweight")
    print("2. Torrent (qBittorrent) - Requires qBit App")
    print("3. Dropbox Mode")
    choice = input("Enter choice (1-3): ").strip()
    
    mode = "dropbox"
    
    if choice == "1":
        mode = "torrent_aria"
    elif choice == "2":
        mode = "torrent_qbit"
        # Initial check for qBittorrent connection, though clients are instantiated per song
        if qbittorrentapi:
            try:
                client = qbittorrentapi.Client(host=settings.QBIT_HOST, username=settings.QBIT_USER, password=settings.QBIT_PASS)
                client.auth_log_in()
                logger.info(f"Connected to qBittorrent: {client.app.version}")
            except Exception as e:
                logger.error(f"Failed to connect to qBittorrent: {e}")
                print("Could not connect to qBittorrent. Exiting.")
                return
        else:
            print("qbittorrent-api not installed. Cannot use qBittorrent mode.")
            return

    if not Path(file_path).exists():
        logger.error(f"Songs file not found: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        songs = [line.strip() for line in f if line.strip()]

    logger.info(f"Found {len(songs)} songs to process. Starting parallel pool (Max 4)...")
    
    # Parallel Processing using ThreadPoolExecutor
    MAX_WORKERS = 4 
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for song_query in songs:
             executor.submit(process_single_song, song_query, mode)

if __name__ == "__main__":
    songs_file = sys.argv[1] if len(sys.argv) > 1 else "songs.txt"
    try:
        process_batch(songs_file)
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
