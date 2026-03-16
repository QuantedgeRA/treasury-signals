# Treasury Purchase Signal Intelligence

Automated alerts when Bitcoin treasury companies are about to buy BTC.

## Quick Start

1. **Get your API key** from [twitterapi.io](https://twitterapi.io)

2. **Create your `.env` file:**
   - Copy `.env.example` to `.env`
   - Replace the placeholder with your real API key

3. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

4. **Test the API connection:**
   ```
   python twitter_client.py
   ```

5. **Run the full scanner:**
   ```
   python main.py
   ```

## Project Structure

```
treasury-signals/
├── .env                 # Your secret API keys (DO NOT COMMIT)
├── .env.example         # Template showing what keys you need
├── .gitignore           # Tells Git to ignore .env
├── main.py              # Main script - run this
├── twitter_client.py    # Talks to TwitterAPI.io
├── accounts.json        # List of X accounts to monitor
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## Build Phases

- **Week 1:** Fetch and display tweets (current)
- **Week 2:** Database + duplicate detection + polling loop
- **Week 3:** Signal classifier (purchase hint detection)
- **Week 4:** Telegram bot + cloud deployment
- **Week 5-6:** Tune accuracy, expand accounts, launch
