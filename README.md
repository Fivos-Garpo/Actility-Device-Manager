# Actility Device Manager

Python/Tkinter desktop application for managing LoRaWAN devices in Actility ThingPark Enterprise.

## Features

- Create OTAA devices from Excel
- Get device information
- Delete devices
- Update connectivity
- Update ThingPark domain
- Restart devices by resetting and restoring the connectivity plan
- Batch processing with configurable worker threads
- CSV/Excel result export
- Activity log and batch progress

## Project files

- `Actility_API_v.1.py` — main desktop application
- `token_manager.py` — OAuth token management

## Local secrets

The application expects local secret files that are **not committed to GitHub**:

- `credentials.txt`
- `token.txt`
- `service_account.txt`

Keep these files only on the local machine. Never commit them or paste their contents into chat.

## Setup

1. Install Python 3.x.
2. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

3. Create `credentials.txt` beside the Python scripts with:

   ```
   client_id=YOUR_CLIENT_ID
   client_secret=YOUR_CLIENT_SECRET
   ```

4. Run:

   ```
   python Actility_API_v.1.py
   ```

