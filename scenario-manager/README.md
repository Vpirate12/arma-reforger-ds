# 🎮 Scenario Manager for Spare Time Gaming

A secure web interface to manage Arma Reforger scenarios from anywhere, hosted on your Unraid server with Cloudflare Tunnel.

## Features

✅ **View all scenarios** with details (map, mods, players)  
✅ **Upload new scenarios** (JSON files)  
✅ **Mark scenario as active** (your current/default scenario)  
✅ **Download scenarios** to load in Longbow  
✅ **Delete unused scenarios**  
✅ **Secure login** with username/password  
✅ **Accessible worldwide** via Cloudflare Tunnel (IP hidden)  

## Quick Start

### 1. Copy Files to Unraid

```bash
# SSH into your Unraid
ssh root@your-unraid-ip

# Create app directory
mkdir -p /mnt/user/appdata/scenario-manager
mkdir -p /mnt/user/scenarios

# Copy all files there
# (use SFTP or SSH copy)
```

### 2. Create User Accounts

```bash
cd /mnt/user/appdata/scenario-manager

# Create your user
docker run -it --rm \
  -v $(pwd):/app \
  python:3.11-slim \
  sh -c "cd /app && pip install werkzeug && python setup.py yourusername yourpassword"
```

### 3. Start the App

```bash
docker-compose up -d
```

### 4. Setup Cloudflare Tunnel

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for step-by-step instructions.

Once done, access at: `https://scenarios.yourdomain.com`

## File Structure

```
scenario-manager/
├── app.py                 # Flask backend
├── requirements.txt       # Python dependencies
├── docker-compose.yml     # Docker configuration
├── setup.py              # User management script
├── templates/
│   ├── login.html        # Login page
│   └── dashboard.html    # Main interface
├── DEPLOYMENT_GUIDE.md   # Full setup guide
└── README.md             # This file
```

## Usage

### Login
Enter your username and password

### Upload Scenario
Drag and drop a `.json` file, or click to browse

### Set Active
Click "Set Active" to mark a scenario as current

### Download
Download the JSON to load in Longbow

### Delete
Remove a scenario you no longer need

## Security

- ✅ Password-protected login
- ✅ Cloudflare Tunnel hides your IP
- ✅ HTTPS encryption
- ✅ Session-based authentication
- ✅ Input validation on uploads

## Tech Stack

- **Backend:** Python Flask
- **Frontend:** HTML/CSS/JavaScript
- **Database:** SQLite
- **Hosting:** Docker on Unraid
- **Access:** Cloudflare Tunnel (secure external access)

## Troubleshooting

**App won't start?**
```bash
docker logs scenario-manager
```

**Can't access from outside?**
Check Cloudflare tunnel: `systemctl status cloudflare-tunnel.service`

**Forgot password?**
See "Troubleshooting" in DEPLOYMENT_GUIDE.md

## License

Free to use for personal/community servers

## Support

See DEPLOYMENT_GUIDE.md for detailed help
