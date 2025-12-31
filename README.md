python -m rd_automator.cli start
python dab.py -- login 
python dab.py -- search hello
python dab.py batch songs.txt

cd "c:\Users\itsme\Desktop\music web\client"
npm run dev

cd "c:\Users\itsme\Desktop\music web\server"
npm start


# Real-Debrid Torrent Automator

A modular automation tool that watches a local directory, automatically processes new files, and sends them to Real-Debrid for downloading.

It supports two modes:
1.  **Torrent Mode**: Creates a torrent, seeds it using Aria2c locally, and uploads the .torrent to RD.
2.  **Hoster Mode**: Uploads the file to BayFiles (anonymous hoster) and then unrestricts the link on RD.

## Features

- **Directory Monitoring**: Watch for new files added to a specific folder.
- **Auto-Seeding**: Uses **Aria2c** to seed files locally so Real-Debrid can download them instantly even if there are no other seeders (Torrent Mode).
- **Hoster Upload**: Direct upload support via BayFiles for situations where torrenting is not preferred (Hoster Mode).
- **Real-Debrid Integration**: Uploads torrents/links via API and starts downloads.
- **Lifecycle Management**: Automatically stops seeding once RD reports the download is complete (Torrent Mode).
- **CLI Interface**: Easy to use commands for start and status.
- **Docker Support**: Containerized deployment available.

## Installation

### Prerequisites

- Python 3.9+
- A Real-Debrid Account with Premium (API token required).
- **Aria2c**: Must be installed and available in your System PATH (Required for Torrent Mode).
    - [Download Aria2c](https://github.com/aria2/aria2/releases)

### Local Setup

1.  **Clone the repository**:
    ```bash
    git clone <repo-url>
    cd rd_automator
    ```

2.  **Install Dependencies**:
    ```bash
    # Create virtual environment (recommended)
    python -m venv venv
    
    # Windows
    .\venv\Scripts\activate
    # Linux/Mac
    source venv/bin/activate

    # Install requirements
    pip install -r requirements.txt
    ```

3.  **Configuration**:
    - Rename `.env.example` to `.env` and add your RD API Token.
    - Rename `config.yaml.example` to `config.yaml` and adjust settings.

## Configuration

Edit `config.yaml` to change modes:

```yaml
# Upload Mode: "torrent" (default) or "hoster"
upload_mode: "torrent" 
```

- **torrent**: Creates .torrent -> Seeds locally -> Uploads to RD.
- **hoster**: Uploads file to BayFiles -> Unrestricts link on RD.

## Usage

### CLI Commands

- **Start Watching**:
    ```bash
    python -m rd_automator.cli start
    ```
    This will begin monitoring the `watch_path`.

- **Check Status**:
    ```bash
    python -m rd_automator.cli status
    ```
    Displays current user status from Real-Debrid.

- **Open Config**:
    ```bash
    python -m rd_automator.cli config
    ```
    Opens the configuration file.

python -m rd_automator.cli start