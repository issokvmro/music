from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
import json
import logging
import sys

# Configure logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

def scrape_spotify_playlist(url):
    try:
        logging.info(f"Scraping Spotify URL: {url}")
        response = cffi_requests.get(url, impersonate="chrome120")
        if response.status_code != 200:
            logging.error(f"Spotify scrape failed status: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.content, 'html.parser')
        tracks = []
        
        # DEBUG: Save HTML to inspect
        with open("debug_spotify.html", "wb") as f:
            f.write(response.content)
        logging.info("Saved debug_spotify.html")

        # Method 1: Parse __NEXT_DATA__
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
                            tracks.append(f"{artist} - {title}")
                    
                    logging.info(f"Found {len(tracks)} tracks in __NEXT_DATA__")
                    return tracks
            except Exception as e:
                logging.error(f"Error parsing NEXT_DATA: {e}")
                
        # Method 2: Fallback (unlikely needed for embed)
        return []

    except Exception as e:
        logging.error(f"Scrape error: {e}")
        return []

if __name__ == "__main__":
    # Test with Global Top 50
    url = "https://open.spotify.com/embed/playlist/3EzLEpQbVE1L3sZL3TvsHy" 
    tracks = scrape_spotify_playlist(url)
    print(f"Found {len(tracks)} tracks:")
    for t in tracks[:5]:
        print(f" - {t}")
