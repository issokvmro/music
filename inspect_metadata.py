from unified_automator import DABClient
import json

def inspect():
    client = DABClient()
    client.login()
    # Search for a song known to have good metadata
    results = client.search("Thriller Michael Jackson")
    if results:
        print(json.dumps(results[0], indent=2))
    else:
        print("No results found")

if __name__ == "__main__":
    inspect()
