# CalBot - AI Calendar Assistant

CalBot is an intelligent calendar assistant that helps you manage your Cal.com calendar through natural language conversations. Book meetings, check availability, cancel events, and reschedule appointments using simple chat commands.

## Features

- 📅 **Book Meetings**: "Book a meeting tomorrow at 2pm"
- 📋 **List Events**: "Show me my scheduled events"
- ❌ **Cancel Meetings**: "Cancel my 3pm meeting today"
- 🔄 **Reschedule Events**: "Move my 2pm meeting to 3pm"
- 🕐 **Check Availability**: Automatically checks time slots before booking
- 🌐 **Web Interface**: Clean, interactive chat interface
- 📱 **REST API**: Integration-ready API endpoints

## Quick Start

### 1. Prerequisites

- Python 3.8+
- Cal.com account with API access
- OpenAI API key

### 2. Installation

```bash
# Clone or download the project files
# Install required packages
pip install fastapi uvicorn langchain-openai langgraph python-dotenv requests pytz
```

### 3. Configuration

Create a `.env` file in the project directory:

```env
CALCOM_API_KEY=your_calcom_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
USER_EMAIL=your-email@example.com
USER_TIMEZONE=America/Los_Angeles
```

**Getting your Cal.com API key:**
1. Go to [Cal.com Settings](https://app.cal.com/settings/developer/api-keys)
2. Create a new API key
3. Copy the key to your `.env` file

### 4. Run the Application

```bash
# Start the web server
python chatbot_server.py
```

Open your browser and navigate to: **http://localhost:8000**

## Usage Examples

### Natural Language Commands

- **"Book a meeting on 7/31/2025 @ 3pm"**
- **"Show me my events for this week"**
- **"Cancel my meeting at 2pm tomorrow"**
- **"Reschedule my 10am meeting to 11am"**
- **"What meeting types are available?"**

### Supported Date Formats

- Relative: `today`, `tomorrow`, `next Monday`
- US Format: `7/31/2025`, `12/25/2024`
- ISO Format: `2025-07-31`
- Natural: `July 31st, 2025`, `Dec 25th`

### Supported Time Formats

- 12-hour: `2pm`, `2:30 PM`, `10:00 AM`
- 24-hour: `14:30`, `22:00`
- Flexible: `2`, `at 3pm`, `@ 2:30`

## File Structure

```
calbot/
├── cal.py              # Core calendar logic and Cal.com API integration
├── chatbot_server.py   # FastAPI web server and chat interface
├── templates/
│   └── chat.html       # Web interface (auto-created)
├── .env               # Environment variables (you create this)
└── README.md          # This file
```

## API Endpoints

### REST API
- **POST** `/chat` - Send a message and get a response
  ```json
  {
    "message": "Book a meeting tomorrow at 2pm"
  }
  ```

### WebSocket
- **WS** `/ws` - Real-time chat interface

### Health Check
- **GET** `/health` - Application status

## Command Line Usage

You can also run CalBot in terminal mode:

```bash
python cal.py
```

This provides a command-line interface for testing and direct interaction.

## Troubleshooting

### Common Issues

**"API key not configured"**
- Ensure your `.env` file has the correct `CALCOM_API_KEY`
- Verify the API key is valid in your Cal.com settings

**"No event types found"**
- Create event types in your Cal.com dashboard first
- Check that your API key has proper permissions

**"Date parsing error"**
- Use supported date formats (see examples above)
- Try relative dates like "tomorrow" or "next Monday"

**"Time slot not available"**
- CalBot will suggest alternative times
- Check your Cal.com availability settings

### Debug Mode

For detailed logging, check the terminal output when running the server. Error messages will help identify specific issues.

## Development

### Adding New Features

- **New tools**: Add to `cal.py` and update the `tools` list
- **Custom parsing**: Modify `parse_date_flexible()` or `parse_time_flexible()`
- **UI changes**: Update the HTML template in `templates/chat.html`

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CALCOM_API_KEY` | Your Cal.com API key | Required |
| `OPENAI_API_KEY` | Your OpenAI API key | Required |
| `USER_EMAIL` | Your email for bookings | Required |
| `USER_TIMEZONE` | Your timezone | `America/Los_Angeles` |

## Support

For issues related to:
- **Cal.com API**: Check [Cal.com API Documentation](https://developer.cal.com/)
- **OpenAI API**: Check [OpenAI API Documentation](https://platform.openai.com/docs)
- **CalBot functionality**: Review the error messages in terminal output

