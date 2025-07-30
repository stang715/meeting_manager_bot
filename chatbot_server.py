# chatbot_server.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage, SystemMessage, ToolMessage
from typing import List, Dict
import asyncio
import uvicorn
import os
import re
import logging
from datetime import datetime, timedelta
import json
from datetime import datetime

# Import everything from cal.py
from cal import (
    list_event_types,
    check_availability,
    book_meeting,
    list_scheduled_events,
    cancel_event,
    reschedule_event,
    AgentState,
    model,
    tools,
    USER_EMAIL,
    USER_TIMEZONE
)


logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CalBot Web API")
templates = Jinja2Templates(directory="templates")

# Create directories if they don't exist
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)


# Tool execution function
def execute_tool(tool_call):
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    
    try:
        # Execute the actual tool from cal.py
        result = globals()[tool_name].invoke(tool_args)
        
        # Add detailed logging for debugging
        logging.info(f"Tool {tool_name} executed with args: {tool_args}")
        logging.info(f"Tool {tool_name} result: {result}")

        # Handle specific tools with custom logic
         
        # BOOK MEETING - Handle conflicts and errors better
        if tool_name == "book_meeting":
            # Return exactly what the book_meeting function returns
            return str(result)

        # RESCHEDULE EVENT - Pass through the comprehensive response
        elif tool_name == "reschedule_event":
            # Return exactly what the reschedule_event function returns
            return str(result)

        # CANCEL EVENT - Pass through the actual response
        elif tool_name == "cancel_event":
            return str(result)

        # CHECK AVAILABILITY - Pass through the response
        elif tool_name == "check_availability":
            return str(result)

        # LIST EVENT TYPES - Pass through the response
        elif tool_name == "list_event_types":
            return str(result)

        # LIST SCHEDULED EVENTS - Pass through the response
        elif tool_name == "list_scheduled_events":
            return str(result)

        # Default case - return the actual result
        return str(result)

    except Exception as e:
        logging.error(f"Tool error in {tool_name}: {str(e)}")
        return f"⚠️ Sorry, I encountered an error with {tool_name}. Please try again."



# this class is set to handle conversation context
# This will help manage pending actions like bookings, cancellations, etc.
class ConversationContext:
    def __init__(self):
        self.pending_action = None
        self.pending_data = {}
        
    def set_pending_booking(self, event_type_id, date, suggested_time, original_time):
        self.pending_action = "booking_confirmation"
        self.pending_data = {
            "event_type_id": event_type_id,
            "date": date,
            "suggested_time": suggested_time,
            "original_time": original_time
        }
    
    def clear(self):
        self.pending_action = None
        self.pending_data = {}


def handle_smart_booking(user_message: str) -> str:
    """Handle booking requests with automatic availability checking"""
    import re
    
    # Check if this is a booking request
    if not "book" in user_message.lower():
        return None
    
    # Extract event type ID with default to 15 min meeting
    event_type_mapping = {
        "15 min meeting": 2886675,
        "30 min meeting": 2886676,
        "secret meeting": 2886677
    }
    
    event_type_id = 2886675  # Default to 15 min meeting
    event_type_name = "15 Min Meeting"
    
    # Check if user specified a different meeting type
    for event_name, event_id in event_type_mapping.items():
        if event_name in user_message.lower():
            event_type_id = event_id
            event_type_name = event_name.title()
            break
    
    # Extract time with more flexible patterns
    time_patterns = [
        r'@\s*(\d{1,2}:\d{2}\s*[ap]m)',   # "@ 3:00 PM"
        r'@\s*(\d{1,2}\s*[ap]m)',         # "@ 3pm" or "@ 3 PM"
        r'at\s*(\d{1,2}:\d{2}\s*[ap]m)',  # "at 3:00 PM"
        r'at\s*(\d{1,2}\s*[ap]m)',        # "at 3pm"
        r'(\d{1,2}:\d{2}\s*[ap]m)',       # "3:00 PM"
        r'(\d{1,2}\s*[ap]m)',             # "3 PM" or "3pm"
        r'(\d{1,2}:\d{2})',               # "15:00"
        r'at\s+(\d{1,2})',                # "at 3"
        r'(\d{1,2})'                      # Just "3"
    ]
    
    time_str = None
    for pattern in time_patterns:
        match = re.search(pattern, user_message.lower())
        if match:
            raw_time = match.group(1)
            # Use the flexible parser from cal.py
            from cal import parse_time_flexible
            try:
                time_str = parse_time_flexible(raw_time)
                break
            except:
                continue
    
    if not time_str:
        return None
    
    # Extract date using flexible parsing
    date_str = None
    
    # Look for specific date patterns first
    date_patterns = [
        r'(\d{1,2}/\d{1,2}/\d{2,4})',     # MM/DD/YYYY or M/D/YY
        r'(\d{4}-\d{1,2}-\d{1,2})',       # YYYY-MM-DD
        r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}',  # "July 31, 2025"
        r'\d{1,2}(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec),?\s*\d{4}',  # "31st July 2025"
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, user_message.lower())
        if match:
            date_str = match.group(0)
            break
    
    # If no specific date found, check for relative dates
    if not date_str:
        if "tomorrow" in user_message.lower():
            date_str = "tomorrow"
        elif "today" in user_message.lower():
            date_str = "today"
        else:
            date_str = "tomorrow"  # Default fallback
    
    # First check availability
    availability_result = check_availability.invoke({
        "event_type_id": event_type_id,
        "date": date_str,
        "requested_time": time_str
    })
    
    # If time is available, book directly
    if "✅" in availability_result and "is available" in availability_result:
        booking_result = book_meeting.invoke({
            "event_type_id": event_type_id,
            "date": date_str,
            "time": time_str,
            "attendee_name": USER_EMAIL.split('@')[0],
            "attendee_email": USER_EMAIL,
            "reason": f"Booked via CalBot - {event_type_name}"
        })
        
        # Return a more detailed success message
        if "✅ Meeting booked successfully" in booking_result:
            return f"✅ {event_type_name} successfully booked!\n\n{booking_result}"
        else:
            return booking_result
    
    # If not available, return the availability result with meeting type info
    if "❌" in availability_result:
        return f"{availability_result}\n\n📝 Note: This will be a {event_type_name}. If you prefer a 30 Min Meeting or Secret Meeting, please specify."
    
    return availability_result




# Agent workflow function

def run_agent_workflow(user_message: str, ws: WebSocket = None) -> str:
    """Run the complete agent workflow with conversation state"""
    # Handle confirmation responses
    if ws and ws in manager.contexts:
        context = manager.contexts[ws]
        user_msg_lower = user_message.lower().strip()
        
        if user_msg_lower in ['yes', 'y', 'sure', 'ok', 'okay', 'confirm']:
            if context.pending_action == "booking_confirmation":
                # Execute the pending booking
                booking_result = book_meeting.invoke({
                    "event_type_id": context.pending_data["event_type_id"],
                    "date": context.pending_data["date"],
                    "time": context.pending_data["suggested_time"],
                    "attendee_name": USER_EMAIL.split('@')[0],
                    "attendee_email": USER_EMAIL,
                    "reason": "Booked via CalBot confirmation"
                })
                context.clear()
                return booking_result
        elif user_msg_lower in ['no', 'n', 'nope', 'cancel']:
            if context.pending_action == "booking_confirmation":
                context.clear()
                return "❌ Booking cancelled. Would you like to try a different time?"
        elif user_msg_lower in ['reschedule', 'change time', 'modify']:
            if context.pending_action == "booking_confirmation":
                context.clear()
                return "🔄 Please provide the new date and time for rescheduling."
    else:
        context = ConversationContext()
        if ws:
            manager.contexts[ws] = context  
    # Add system prompt
    current_datetime_str = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
    system_prompt = SystemMessage(content=f"""
        You are CalBot, an AI assistant that helps users manage their calendar through Cal.com.

        # Context
        - Current time: {current_datetime_str}
        - User email: {USER_EMAIL}
        - User timezone: {USER_TIMEZONE}

        # Booking Workflow
        1. When user requests to book a meeting:
            a. If they specify event type, date, and time in one message, proceed directly
            b. If missing details, ask for them specifically
            c. Once you have all details (event type ID, date, time), book immediately
            d. Don't ask for confirmation if user already provided all details
        2. If booking fails, explain the specific reason and suggest alternatives
        3. If booking succeeds, show the confirmation message exactly as returned

        # Cancellation Workflow
        1. When user requests to cancel a meeting:
            a. Use cancel_event tool immediately with provided time and date
            b. Show the exact result from the cancellation
        2. Don't list events first unless cancellation fails

        # Rescheduling Workflow
        1. When user requests to reschedule:
            a. Extract old time, new time, and date from the message
            b. Use reschedule_event tool immediately
            c. Show the exact result from the reschedule operation
        2. Don't break rescheduling into separate cancel and book steps
        3. If rescheduling fails, explain why and suggest alternatives

        # Schedule Listing Workflow
        1. When user asks to see their schedule/events/meetings:
            a. IMMEDIATELY use the list_scheduled_events tool
            b. Display the results in a clean, readable format
            c. If no events found, suggest booking a new one

        # Important Rules
        - Always use the exact responses from tools - don't modify success/error messages
        - If a tool returns a detailed error, show it to help the user understand
        - For booking, if user provides "Book meeting tomorrow 2pm 15 Min Meeting", extract:
        * date: "tomorrow" 
        * time: "2:00 PM"
        * event_type_id: find ID for "15 Min Meeting"
        - Don't ask for confirmations when user has already provided complete details
        """)
    
    messages = [system_prompt, HumanMessage(content=user_message)]

    # Try smart booking first for simple booking requests
    smart_booking_result = handle_smart_booking(user_message)
    if smart_booking_result:
        # Check if this is a booking confirmation setup
        if ws and "Would you like to book" in smart_booking_result and "instead?" in smart_booking_result:
            # Extract booking details for context
            if "book" in user_message.lower():
                import re
                time_match = re.search(r'(\d{1,2}:\d{2}\s*[ap]m|\d{1,2}\s*[ap]m)', user_message.lower())
                if time_match:
                    original_time = time_match.group(1)
                    # Extract suggested time from result
                    suggested_match = re.search(r'Closest available time: (\d{1,2}:\d{2} [AP]M)', smart_booking_result)
                    if suggested_match:
                        suggested_time = suggested_match.group(1)
                        date_str = "tomorrow" if "tomorrow" in user_message.lower() else "today"
                        
                        manager.contexts[ws].set_pending_booking(
                            event_type_id=2886675,  # Default 15 min meeting
                            date=date_str,
                            suggested_time=suggested_time,
                            original_time=original_time
                        )
        
        return smart_booking_result
    # If no smart booking, continue with the agent graph

    max_iterations = 5
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        response = model.invoke(messages)
        messages.append(response)
        
        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_result = execute_tool(tool_call)
                
                if (tool_call["name"] == "reschedule_event" and 
                    ("✅ Reschedule completed successfully" in tool_result or 
                     "⚠️ Reschedule partially completed" in tool_result)):
                    return tool_result
                
                tool_message = ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_call["id"]
                )
                messages.append(tool_message)
            
            continue
        else:
            return response.content
    
    return "I apologize, but I wasn't able to complete your request. Please try again."




# ---------- REST endpoints ----------
class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """
    REST endpoint: POST /chat  {"message": "book a meeting tomorrow 2pm"}
    """
    try:
        reply = run_agent_workflow(req.message)
        return {"reply": reply}
    except Exception as e:
        logging.error(f"Error in chat endpoint: {str(e)}")
        return {"reply": f"Sorry, I encountered an error: {str(e)}"}

# ---------- WebSocket real-time chat ----------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.conversation_states: Dict[WebSocket, List[BaseMessage]] = {}
        self.contexts: Dict[WebSocket, ConversationContext] = {}  # Add this line

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)
        self.conversation_states[ws] = []
        self.contexts[ws] = ConversationContext()  # Add this line

    async def disconnect(self, ws: WebSocket):
        if ws in self.active_connections:
            self.active_connections.remove(ws)
        if ws in self.conversation_states:
            del self.conversation_states[ws]
        if ws in self.contexts:  # Add this block
            del self.contexts[ws]

    async def send_message(self, message: str, ws: WebSocket):
        """Send a message to a specific WebSocket connection"""
        try:
            await ws.send_text(message)
        except Exception as e:
            logging.error(f"Error sending message: {str(e)}")
            await self.disconnect(ws)

    async def broadcast(self, message: str):
        """Send a message to all active connections"""
        for connection in self.active_connections:
            await self.send_message(message, connection)




manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send greeting only once when connection is established
        await manager.send_message(
            "Hello! I'm CalBot, your calendar assistant. How can I help you today?",
            ws
        )
        
        while True:
            data = await ws.receive_text()
            logging.info(f"Received: {data}")
            
            try:
                reply = run_agent_workflow(data, ws)
                await manager.send_message(reply, ws)
                
            except Exception as e:
                error_msg = "❌ Sorry, I encountered an error. Please try again."
                await manager.send_message(error_msg, ws)
                logging.error(f"WebSocket error: {str(e)}")
                
    except WebSocketDisconnect:
        await manager.disconnect(ws)



# ---------- Simple HTML/JS page ----------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# ---------- Static files ----------
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    # Check if required environment variables are set
    if not os.getenv('CALCOM_API_KEY'):
        print("❌ Error: CALCOM_API_KEY not found in environment variables")
        print("Please add CALCOM_API_KEY=your_api_key to your .env file")
        exit(1)
    
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ Error: OPENAI_API_KEY not found in environment variables") 
        print("Please add OPENAI_API_KEY=your_api_key to your .env file")
        exit(1)
    
    print("\n🗓️  ===== CALBOT WEB SERVER =====")
    print("🌐 Starting web server on http://localhost:8000")
    print("💡 Open your browser and navigate to http://localhost:8000")
    print("📝 You can also use the REST API at POST /chat")
    print("=" * 50)
    
    uvicorn.run("chatbot_server:app", host="0.0.0.0", port=8000, reload=True)