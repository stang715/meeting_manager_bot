from typing import Annotated, Sequence, TypedDict, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import requests
from datetime import datetime, timedelta
from pydantic.v1 import BaseModel, Field 
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
import json
import pytz

load_dotenv()

# Cal.com API configuration
CALCOM_API_KEY = os.getenv('CALCOM_API_KEY')
CALCOM_BASE_URL = "https://api.cal.com/v1"
USER_EMAIL = os.getenv('USER_EMAIL', 'your-email@example.com')
USER_TIMEZONE = os.getenv('USER_TIMEZONE', 'America/Los_Angeles')  # Add this to .env

# 1. Add helper function to manage date and time parsing:
def parse_time_flexible(time_str: str) -> str:
    """Parse various time formats into standard format"""
    import re
    
    time_str = time_str.strip().lower()
    
    # Handle formats like "2pm", "2 pm", "2:30pm", "2:30 pm", "14:00", "2"
    patterns = [
        r'(\d{1,2}):(\d{2})\s*(am|pm)',  # "2:30 pm"
        r'(\d{1,2})\s*(am|pm)',          # "2 pm" or "2pm"
        r'(\d{1,2}):(\d{2})',            # "14:30"
        r'(\d{1,2})'                     # "14" or "2"
    ]
    
    for pattern in patterns:
        match = re.match(pattern, time_str)
        if match:
            groups = match.groups()
            
            if len(groups) == 3:  # Hour:Minute AM/PM
                hour, minute, period = groups
                return f"{hour}:{minute} {period.upper()}"
            elif len(groups) == 2:  # Hour AM/PM or Hour:Minute
                if groups[1] in ['am', 'pm']:  # Hour AM/PM
                    hour, period = groups
                    return f"{hour}:00 {period.upper()}"
                else:  # Hour:Minute (24-hour)
                    hour, minute = groups
                    hour_int = int(hour)
                    if hour_int > 12:
                        return f"{hour}:{minute}"
                    else:
                        # Convert to 12-hour format
                        if hour_int == 0:
                            return f"12:{minute} AM"
                        elif hour_int == 12:
                            return f"12:{minute} PM"
                        elif hour_int > 12:
                            return f"{hour_int - 12}:{minute} PM"
                        else:
                            return f"{hour}:{minute} AM"
            elif len(groups) == 1:  # Just hour
                hour = int(groups[0])
                if hour > 12:
                    # 24-hour format
                    if hour == 0:
                        return "12:00 AM"
                    elif hour > 12:
                        return f"{hour - 12}:00 PM"
                    else:
                        return f"{hour}:00 AM"
                else:
                    # Assume business hours: 1-11 are PM unless clearly morning context
                    if hour >= 7 and hour <= 11:
                        return f"{hour}:00 AM"
                    else:
                        return f"{hour}:00 PM"
    
    # If no pattern matches, return original
    return time_str

def parse_date_flexible(date_str: str) -> tuple:
    """Parse various date formats and return (date_obj, date_for_api_string)"""
    import re
    from datetime import datetime, timedelta
    
    date_str = date_str.strip().lower()
    today = datetime.now().date()
    
    # Handle relative dates
    if date_str in ["today"]:
        return today, "today"
    elif date_str in ["tomorrow"]:
        date_obj = today + timedelta(days=1)
        return date_obj, "tomorrow"
    elif "day after tomorrow" in date_str:
        date_obj = today + timedelta(days=2)
        return date_obj, date_obj.strftime("%Y-%m-%d")
    elif date_str in ["yesterday"]:
        date_obj = today - timedelta(days=1)
        return date_obj, date_obj.strftime("%Y-%m-%d")
    
    # Handle weekday references
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for i, day in enumerate(weekdays):
        if f"this {day}" in date_str:
            days_ahead = i - today.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            date_obj = today + timedelta(days=days_ahead)
            return date_obj, date_obj.strftime("%Y-%m-%d")
        elif f"next {day}" in date_str:
            days_ahead = i - today.weekday() + 7
            date_obj = today + timedelta(days=days_ahead)
            return date_obj, date_obj.strftime("%Y-%m-%d")
        elif f"last {day}" in date_str:
            days_back = today.weekday() - i
            if days_back <= 0:
                days_back += 7
            date_obj = today - timedelta(days=days_back)
            return date_obj, date_obj.strftime("%Y-%m-%d")
    
    # Handle "next week", "this week"
    if "next week" in date_str:
        date_obj = today + timedelta(days=7)
        return date_obj, date_obj.strftime("%Y-%m-%d")
    elif "this week" in date_str:
        return today, "this week"
    
    # Handle various date formats with multiple patterns
    patterns = [
        # MM/DD/YYYY, M/D/YYYY, MM/DD/YY, M/D/YY - FIXED ORDER
        (r'(\d{1,2})/(\d{1,2})/(\d{2,4})', lambda m: parse_mdy(m[0], m[1], m[2])),
        # YYYY-MM-DD, YYYY/MM/DD
        (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', lambda m: datetime.strptime(f"{m[0]}-{m[1]:0>2}-{m[2]:0>2}", "%Y-%m-%d").date()),
        # Month DD, YYYY or Month DD (assume current year)
        (r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?', 
         lambda m: parse_month_day_year(m[0], m[1], m[2] if m[2] else str(today.year))),
        # DD Month, YYYY or DD Month (assume current year)
        (r'(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?,?\s*(\d{4})?',
         lambda m: parse_month_day_year(m[1], m[0], m[2] if m[2] else str(today.year))),
        # ISO format variations
        (r'(\d{4})(\d{2})(\d{2})', lambda m: datetime.strptime(f"{m[0]}-{m[1]}-{m[2]}", "%Y-%m-%d").date()),
    ]
    
    def parse_mdy(month, day, year):
        """Helper to parse MM/DD/YYYY format"""
        month = int(month)
        day = int(day)
        year = int(year)
        
        # Handle 2-digit years
        if year < 100:
            year += 2000 if year < 50 else 1900
        
        # Validate month and day ranges
        if month < 1 or month > 12:
            raise ValueError(f"Invalid month: {month}")
        if day < 1 or day > 31:
            raise ValueError(f"Invalid day: {day}")
            
        try:
            return datetime(year, month, day).date()
        except ValueError as e:
            raise ValueError(f"Invalid date: {month}/{day}/{year} - {str(e)}")
    
    def parse_month_day_year(month_str, day, year):
        """Helper to parse month name formats"""
        month_dict = {
            'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3,
            'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6,
            'july': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9, 'sep': 9,
            'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12
        }
        month_num = month_dict.get(month_str.lower())
        if month_num:
            return datetime(int(year), month_num, int(day)).date()
        raise ValueError(f"Unknown month: {month_str}")
    
    # Try each pattern
    for pattern, converter in patterns:
        match = re.search(pattern, date_str, re.IGNORECASE)
        if match:
            try:
                date_obj = converter(match.groups())
                # Validate date is reasonable (not too far in past/future)
                days_diff = abs((date_obj - today).days)
                if days_diff > 365 * 5:  # More than 5 years difference
                    continue  # Try next pattern
                return date_obj, date_obj.strftime("%Y-%m-%d")
            except (ValueError, TypeError) as e:
                print(f"Date parsing error for pattern {pattern}: {e}")  # Debug info
                continue
    
    # Final attempt: try direct parsing as YYYY-MM-DD
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        return date_obj, date_str
    except ValueError:
        pass
    
    # If nothing works, raise error with helpful message
    raise ValueError(f"Could not parse date '{date_str}'. Try formats like 'tomorrow', '7/31/2025', 'July 28th', 'this Thursday', or 'YYYY-MM-DD'")




class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]

def make_calcom_request(endpoint: str, method: str = "GET", data: dict = None):
    """Helper function to make requests to Cal.com API"""
    if not CALCOM_API_KEY:
        return {"error": "Cal.com API key not configured"}
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    params = {"apiKey": CALCOM_API_KEY}
    url = f"{CALCOM_BASE_URL}{endpoint}"
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif method == "POST":
            response = requests.post(url, headers=headers, params=params, json=data, timeout=10)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, params=params, json=data, timeout=10)
        elif method == "PATCH":
            response = requests.patch(url, headers=headers, params=params, json=data, timeout=10)
            
        if response.status_code not in [200, 204]:
            error_text = response.text[:500]
            print(f"❌ API Error: {method} {response.url} - Status: {response.status_code}")
            return {"error": f"API request failed with status {response.status_code}: {error_text}"}
            
        if response.content:
            return response.json()
        return {"success": True, "status_code": response.status_code}
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {str(e)}")
        return {"error": f"Request failed: {str(e)}"}




# start tool definition:


@tool
def list_event_types() -> str:
    """Get available event types for booking"""
    result = make_calcom_request("/event-types")
    
    if "error" in result:
        return f"Error fetching event types: {result['error']}"
    
    if "event_types" in result and result["event_types"]:
        event_list = []
        for event in result["event_types"]:
            event_list.append(f"- {event.get('title', 'Untitled')} (ID: {event.get('id')}) - {event.get('length', 0)} minutes")
        return f"Available event types:\n" + "\n".join(event_list)
    else:
        return "No event types found. You may need to create event types in your Cal.com dashboard first."




@tool
def check_availability(event_type_id: int, date: str, requested_time: str = None) -> str:
    """Check if a specific time is available for booking"""
    try:
        try:
            target_date, _ = parse_date_flexible(date)
        except ValueError as e:
            return f"❌ {str(e)}. Please use formats like 'tomorrow', '7/31/2025', 'July 28th', or 'this Thursday'"

        date_str = target_date.strftime("%Y-%m-%d")

        # Set time bounds for the entire day in user's timezone
        start_time = f"{date_str}T00:00:00.000Z"
        end_time = f"{date_str}T23:59:59.999Z"

        endpoint = f"/slots?eventTypeId={event_type_id}&startTime={start_time}&endTime={end_time}&timeZone={USER_TIMEZONE}"
        result = make_calcom_request(endpoint)

        if "error" in result:
            return f"Error checking availability: {result['error']}"

        # Parse requested time if provided
        requested_slot = None
        if requested_time:
            try:
                # Use flexible time parser first
                parsed_time = parse_time_flexible(requested_time)

                # Convert to 24-hour format for comparison
                if "am" in parsed_time.lower() or "pm" in parsed_time.lower():
                    time_obj = datetime.strptime(parsed_time, "%I:%M %p").time()
                else:
                    time_obj = datetime.strptime(parsed_time, "%H:%M").time()

                requested_time_str = time_obj.strftime("%H:%M")
            except ValueError:
                return f"Couldn't understand the time '{requested_time}'. Please try formats like '2pm', '2:30 PM', or '14:00'"

        # Check availability
        available_slots = []
        exact_match_found = False

        if "slots" in result and isinstance(result["slots"], dict):
            for date_key, slots in result["slots"].items():
                for slot in slots:
                    if isinstance(slot, dict) and "time" in slot:
                        slot_time = slot["time"]
                        try:
                            # Parse the time and convert to user's timezone
                            slot_dt = datetime.fromisoformat(slot_time.replace("Z", "+00:00"))
                            user_tz = pytz.timezone(USER_TIMEZONE)
                            slot_dt = slot_dt.astimezone(user_tz)

                            # Check if this matches the requested time
                            if requested_time:
                                slot_time_str = slot_dt.strftime("%H:%M")
                                if slot_time_str == requested_time_str:
                                    exact_match_found = True
                                    return f"✅ The requested time {requested_time} is available on {target_date.strftime('%A, %B %d')}."

                            # Store for alternative suggestions
                            available_slots.append(slot_dt.strftime("%I:%M %p").lstrip("0"))
                        except ValueError:
                            continue

        if requested_time and not exact_match_found:
            if available_slots:
                # Find the closest available time to the requested time
                try:
                    requested_dt = datetime.strptime(requested_time_str, "%H:%M")
                    requested_minutes = requested_dt.time().hour * 60 + requested_dt.time().minute

                    # Sort available slots by proximity to requested time
                    def time_distance(slot_str):
                        try:
                            slot_dt = datetime.strptime(slot_str, "%I:%M %p")
                            slot_minutes = slot_dt.time().hour * 60 + slot_dt.time().minute
                            return abs(slot_minutes - requested_minutes)
                        except:
                            return 999999  # Put invalid times at the end

                    sorted_slots = sorted(available_slots, key=time_distance)
                    closest_slot = sorted_slots[0]

                    # Get 2-3 closest alternatives (within 2 hours if possible)
                    close_alternatives = []
                    for slot in sorted_slots[1:]:
                        try:
                            slot_dt = datetime.strptime(slot, "%I:%M %p")
                            slot_minutes = slot_dt.time().hour * 60 + slot_dt.time().minute
                            time_diff = abs(slot_minutes - requested_minutes)

                            # Only include alternatives within 2 hours (120 minutes)
                            if time_diff <= 120 and len(close_alternatives) < 2:
                                close_alternatives.append(slot)
                        except:
                            continue
                    
                    alt_text = f"\n\nOther nearby times: {', '.join(close_alternatives)}" if close_alternatives else ""
                    return f"❌ The requested time {requested_time} is not available on {target_date.strftime('%A, %B %d')}.\n\n✅ Closest available time: {closest_slot}{alt_text}\n\nWould you like to book {closest_slot} instead?"
                except:
                    return f"❌ The requested time {requested_time} is not available. Here are available times: {', '.join(available_slots[:3])}\n\nWhich time would you prefer?"
            else:
                return f"❌ No available time slots found for {target_date.strftime('%A, %B %d')}. Please try a different date."

    except Exception as e:
        return f"Error checking availability: {str(e)}"
    



# Updated book_meeting function
@tool
def book_meeting(event_type_id: int, date: str, time: str, attendee_name: str, attendee_email: str = USER_EMAIL, reason: str = "") -> str:
    """Book a meeting at a specific time"""
    try:
        # Parse date with flexible date support - UPDATED SECTION
        try:
            date_obj, date_for_availability = parse_date_flexible(date)
        except ValueError as e:
            return f"❌ {str(e)}. Please use formats like 'tomorrow', '7/31/2025', 'July 28th', or 'this Thursday'"

        # Parse time with flexible format
        try:
            parsed_time = parse_time_flexible(time)
        except ValueError as e:
            return f"❌ Couldn't understand time format: '{time}'. Please try formats like '2pm', '2:30 PM', or '14:00'."
        
        # Check availability first using invoke method
        availability_result = check_availability.invoke({
            "event_type_id": event_type_id,
            "date": date_for_availability,
            "requested_time": parsed_time
        })
        
        if "❌" in availability_result and "is not available" in availability_result:
            return availability_result
        elif "Error checking availability" in availability_result:
            return availability_result

        # Get event type details for duration
        event_type = make_calcom_request(f"/event-types/{event_type_id}")
        if "error" in event_type:
            return f"❌ Error getting event details: {event_type['error']}"
        
        # Handle different response structures
        if "event_type" in event_type:
            duration = event_type["event_type"].get("length", 15)
        else:
            duration = event_type.get("length", 15)

        # Parse the time and create datetime objects
        try:
            # First try to parse with flexible parser
            parsed_time = parse_time_flexible(time)
            
            # Now parse the standardized time
            if "am" in parsed_time.lower() or "pm" in parsed_time.lower():
                time_obj = datetime.strptime(parsed_time, "%I:%M %p").time()
            else:
                time_obj = datetime.strptime(parsed_time, "%H:%M").time()
            
            start_dt = datetime.combine(date_obj, time_obj)
            user_tz = pytz.timezone(USER_TIMEZONE)
            start_dt = user_tz.localize(start_dt)
            end_dt = start_dt + timedelta(minutes=duration)
            
            start_iso = start_dt.astimezone(pytz.UTC).isoformat().replace('+00:00', 'Z')
            end_iso = end_dt.astimezone(pytz.UTC).isoformat().replace('+00:00', 'Z')
            
        except ValueError as e:
            return f"❌ Couldn't understand time format: '{time}'. Please try formats like '2pm', '2:30 PM', or '14:00'."



        # Parse date with flexible date support
        try:
            date_obj, date_for_availability = parse_date_flexible(date)
        except ValueError as e:
            return f"❌ {str(e)}. Please use formats like 'tomorrow', '7/31/2025', 'July 28th', or 'this Thursday'"


        # Create booking data
        booking_data = {
            "eventTypeId": event_type_id,
            "start": start_iso,
            "end": end_iso,
            "responses": {
                "name": attendee_name,
                "email": attendee_email,
                "notes": reason
            },
            "metadata": {},
            "timeZone": USER_TIMEZONE,
            "language": "en"
        }

        print(f"🔄 Booking data: {json.dumps(booking_data, indent=2)}")

        # Make the booking request
        result = make_calcom_request("/bookings", "POST", booking_data)
        
        print(f"🔄 Booking API response: {json.dumps(result, indent=2)}")
        
        if "error" in result:
            error_msg = result['error']
            if "no_available_users_found_error" in str(error_msg):
                return f"❌ This time slot is not available (likely already booked or outside business hours). Please try a different time."
            elif "validation" in str(error_msg).lower():
                return f"❌ Invalid booking data. Please check the date and time format."
            else:
                return f"❌ Error booking meeting: {error_msg}"
        
        # Check for successful booking
        if result.get("booking") or result.get("id"):
            booking = result.get("booking", result)
            
            try:
                if booking.get('startTime'):
                    start_time = datetime.fromisoformat(booking['startTime'].replace('Z', '+00:00'))
                    user_tz = pytz.timezone(USER_TIMEZONE)
                    local_start = start_time.astimezone(user_tz)
                    
                    confirmation = f"✅ Meeting booked successfully for {local_start.strftime('%A, %B %d at %I:%M %p')}."
                    
                    if booking.get("videoCallUrl"):
                        confirmation += f" Video link: {booking['videoCallUrl']}"
                    
                    return confirmation
                else:
                    return f"✅ Meeting booked successfully for {date_obj.strftime('%A, %B %d')} at {parsed_time}."
            except Exception as e:
                return f"✅ Meeting booked successfully for {date_obj.strftime('%A, %B %d')} at {parsed_time}."
        
        return f"❌ Unexpected booking response: {json.dumps(result, indent=2)}"
    
    except Exception as e:
        return f"❌ Error processing booking: {str(e)}"






@tool
def list_scheduled_events(user_email: str = USER_EMAIL) -> str:
    """List all valid upcoming events (excluding canceled ones) from the user's calendar"""
    try:
        # First get all upcoming bookings
        result = make_calcom_request(
            f"/bookings?attendeeEmail={user_email}&status=upcoming"
        )
        
        if "error" in result:
            # Fallback to try without status parameter if needed
            result = make_calcom_request(
                f"/bookings?attendeeEmail={user_email}"
            )
            if "error" in result:
                return f"❌ Calendar Error: {result['error']}"
        
        if not result.get("bookings"):
            return "Your calendar shows no upcoming events."

        # Filter out canceled events and format valid ones
        valid_events = []
        user_tz = pytz.timezone(USER_TIMEZONE)
        
        for booking in result["bookings"]:
            # Skip canceled events
            if booking.get("status", "").upper() == "CANCELLED":
                continue
                
            try:
                start = datetime.fromisoformat(
                    booking["startTime"].replace("Z", "+00:00")
                ).astimezone(user_tz)
                end = datetime.fromisoformat(
                    booking["endTime"].replace("Z", "+00:00")
                ).astimezone(user_tz)
                
                # Format event details
                event_str = (
                    f"• {booking.get('title', 'Meeting')}\n"
                    f"  📅 {start.strftime('%A, %B %d')}\n"
                    f"  🕒 {start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}\n"
                    f"  👥 With: {booking.get('user', {}).get('name', 'Guest')}\n"
                    f"  🔗 Event ID: {booking.get('id', 'N/A')}"
                )
                valid_events.append(event_str)
            except Exception as e:
                print(f"Skipping event due to formatting error: {e}")
                continue

        if not valid_events:
            return "No valid upcoming events found in your calendar."
            
        # Group events by date for better organization
        events_by_date = {}
        for event in valid_events:
            date_line = [line for line in event.split('\n') if '📅' in line][0]
            date = date_line.split('📅 ')[1]
            if date not in events_by_date:
                events_by_date[date] = []
            events_by_date[date].append(event)

        # Build the output with date headers
        output = ["📆 Your Upcoming Schedule:"]
        for date, events in sorted(events_by_date.items()):
            output.append(f"\n📅 {date}")
            output.extend(events)

        return "\n".join(output)

    except Exception as e:
        return f"❌ Failed to fetch calendar: {str(e)}"







@tool
def cancel_event(time: str = None, date_reference: str = None, confirm: bool = False) -> str:
    """Cancel meetings with confirmation. Requires specific time/date or explicit confirmation for bulk actions."""
    try:
        user_tz = pytz.timezone(USER_TIMEZONE)
        today = datetime.now(user_tz).date()
        


        # Parse date range with flexible parsing
        start_date, end_date = today, today
        if date_reference:
            try:
                if date_reference.lower() == "this week":
                    if not confirm:
                        return ("⚠️ Cancelling all events this week is a bulk action. "
                               "Please confirm by repeating the command with 'confirm'")
                    start_date = today
                    end_date = today + timedelta(days=(6 - today.weekday()))
                else:
                    # Use flexible date parser
                    parsed_date, _ = parse_date_flexible(date_reference)
                    start_date = end_date = parsed_date
            except ValueError:
                return f"❌ Could not understand date '{date_reference}'. Please use formats like 'tomorrow', '7/31/2025', 'July 28th', or 'this Thursday'"
            

        # Get bookings in date range
        bookings = make_calcom_request(
            f"/bookings?attendeeEmail={USER_EMAIL}"
            f"&startTime={start_date.isoformat()}T00:00:00Z"
            f"&endTime={end_date.isoformat()}T23:59:59Z"
        )
        
        if "error" in bookings:
            return f"❌ Error fetching bookings: {bookings['error']}"

        # Filter matching bookings
        matching_bookings = []
        for booking in bookings.get("bookings", []):
            if booking.get("status") == "CANCELLED":
                continue
                
            try:
                start_utc = booking['startTime'].replace("Z", "+00:00")
                start_local = datetime.fromisoformat(start_utc).astimezone(user_tz)
                

                # Time filtering - make it more precise
                if time:
                    try:
                        # Parse the requested time
                        parsed_time = parse_time_flexible(time)
                        if "am" in parsed_time.lower() or "pm" in parsed_time.lower():
                            time_obj = datetime.strptime(parsed_time, "%I:%M %p").time()
                        else:
                            time_obj = datetime.strptime(parsed_time, "%H:%M").time()
                            
                        # Exact time match only (no 15-minute tolerance)
                        if not (start_local.time().hour == time_obj.hour and
                               start_local.time().minute == time_obj.minute):
                            continue
                    except ValueError:
                        return f"❌ Invalid time format: {time}. Use '2:00 PM' or '14:00'"
                
                matching_bookings.append(booking)
            except Exception:
                continue

        if not matching_bookings:
            if time:
                return f"✅ No {time} meetings found on {start_date.strftime('%A, %B %d')}"
            return f"✅ No meetings found on {start_date.strftime('%A, %B %d')}"

        # If cancelling multiple without time filter, require confirmation
        if len(matching_bookings) > 1 and not time and not confirm:
            event_list = "\n".join(
                f"- {b.get('title')} at "
                f"{datetime.fromisoformat(b['startTime'].replace('Z','+00:00')).astimezone(user_tz).strftime('%I:%M %p')}"
                for b in matching_bookings[:3]  # Show first 3 as examples
            )
            return (
                f"⚠️ Found {len(matching_bookings)} meetings. Cancelling all requires confirmation.\n"
                f"Example meetings:\n{event_list}\n"
                f"Please confirm by repeating with 'confirm'"
            )

        # Perform cancellations
        results = []
        for booking in matching_bookings:
            result = make_calcom_request(f"/bookings/{booking['id']}", "DELETE")
            if "error" in result:
                results.append(f"❌ Failed to cancel '{booking.get('title')}'")
            else:
                start_time = datetime.fromisoformat(booking['startTime'].replace("Z","+00:00"))
                start_time = start_time.astimezone(user_tz).strftime("%I:%M %p")
                results.append(f"✅ Cancelled '{booking.get('title')}' at {start_time}")

        # Format response
        if len(results) == 1:
            return results[0]
        return f"📅 Cancellation Summary:\n" + "\n".join(results)

    except Exception as e:
        return f"❌ Error during cancellation: {str(e)}"




@tool
def reschedule_event(old_time: str, new_time: str, date_reference: str = "tomorrow", new_date: str = None) -> str:
    """Reschedule a meeting by canceling the old one and booking a new time slot."""
    try:
        user_tz = pytz.timezone(USER_TIMEZONE)
        
        # 1. Parse the old date and find the meeting to reschedule
        if date_reference.lower() == "tomorrow":
            old_date = (datetime.now() + timedelta(days=1)).date()
        elif date_reference.lower() == "today":
            old_date = datetime.now().date()
        else:

        # 1. Parse the old date with flexible parsing
            try:
                old_date, _ = parse_date_flexible(date_reference)
            except ValueError:
                return f"❌ Could not understand date '{date_reference}'. Please use formats like 'tomorrow', '7/31/2025', 'July 28th', or 'this Thursday'"
            
        
        # Get bookings for the specified date BEFORE cancelling
        bookings = make_calcom_request(
            f"/bookings?attendeeEmail={USER_EMAIL}"
            f"&startTime={old_date.isoformat()}T00:00:00Z"
            f"&endTime={old_date.isoformat()}T23:59:59Z"
        )
        
        if "error" in bookings:
            return f"❌ Error finding meeting to reschedule: {bookings['error']}"

        # Find the meeting at the specified time with exact matching
        target_meeting = None
        try:
            parsed_old_time = parse_time_flexible(old_time)
            if "am" in parsed_old_time.lower() or "pm" in parsed_old_time.lower():
                time_obj = datetime.strptime(parsed_old_time, "%I:%M %p").time()
            else:
                time_obj = datetime.strptime(parsed_old_time, "%H:%M").time()
        except ValueError:
            return f"❌ Invalid time format: {old_time}. Use format like '2:00 PM'"

        for booking in bookings.get("bookings", []):
            if booking.get("status") == "CANCELLED":
                continue
                
            try:
                start_utc = booking['startTime'].replace("Z", "+00:00")
                start_local = datetime.fromisoformat(start_utc).astimezone(user_tz)
                
                booking_time = start_local.time()
                # Exact time match only
                if (booking_time.hour == time_obj.hour and 
                    booking_time.minute == time_obj.minute):
                    target_meeting = booking
                    break
            except Exception:
                continue

        if not target_meeting:
            return f"❌ No meeting found at {old_time} on {old_date.strftime('%A, %B %d')} to reschedule."

        # Store original meeting details before cancelling
        original_title = target_meeting.get("title", "Meeting")
        original_start = datetime.fromisoformat(target_meeting['startTime'].replace("Z", "+00:00")).astimezone(user_tz)
        event_type_id = target_meeting.get("eventTypeId")
        
        if not event_type_id:
            return "❌ Could not determine event type for rescheduling"

        # 2. Cancel the original meeting
        cancel_result = make_calcom_request(f"/bookings/{target_meeting['id']}", "DELETE")
        if "error" in cancel_result:
            return f"❌ Failed to cancel original meeting: {cancel_result['error']}"



        # 3. Parse new date with flexible parsing
        if new_date:
            try:
                new_date_obj, new_date_str = parse_date_flexible(new_date)
            except ValueError:
                return f"❌ Could not understand new date '{new_date}'. Please use formats like 'tomorrow', '7/31/2025', 'July 28th', or 'this Thursday'"
        else:
            new_date_obj = old_date
            new_date_str = "today" if old_date == datetime.now().date() else old_date.strftime("%Y-%m-%d")


        # 4. Book the new meeting using invoke method
        book_result = book_meeting.invoke({
            "event_type_id": event_type_id,
            "date": new_date_str,
            "time": new_time,
            "attendee_name": USER_EMAIL.split('@')[0],
            "attendee_email": USER_EMAIL,
            "reason": f"Rescheduled from {old_time} on {old_date.strftime('%B %d')}"
        })
        
        # Parse results and create comprehensive response
        if "✅ Meeting booked successfully" in book_result:            
            return (
                f"✅ Reschedule completed successfully!\n\n"
                f"📅 Original meeting cancelled: {original_title} on {original_start.strftime('%A, %B %d at %I:%M %p')}\n"
                f"📅 New meeting confirmed: {book_result}\n\n"
                f"Is there anything else I can help you with?"
            )
        else:
            # If booking failed, we need to inform about the cancellation
            return (
                f"⚠️ Reschedule partially completed:\n\n"
                f"✅ Original meeting cancelled: {original_title} on {original_start.strftime('%A, %B %d at %I:%M %p')}\n"
                f"❌ New booking failed: {book_result}\n\n"
                f"Please book a new meeting manually or try a different time."
            )

    except Exception as e:
        return f"❌ Error during rescheduling: {str(e)}"


# Define tools
tools = [list_event_types, book_meeting, list_scheduled_events, cancel_event, reschedule_event, check_availability]

# Initialize model with tools
model = ChatOpenAI(model="gpt-4o", temperature=0).bind_tools(tools)





def our_agent(state: AgentState) -> AgentState:
    current_datetime_str = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')

    system_prompt = SystemMessage(content=f"""
    You are CalBot, an AI assistant that helps users manage their calendar through Cal.com.

    # Context
    - Current time: {current_datetime_str}
    - User email: {USER_EMAIL}
    - User timezone: {USER_TIMEZONE}

    # Booking Workflow
    1. When user requests to book a meeting:
        a. First list event types
        b. Then check availability for requested time
        c. If time is available, confirm and book
        d. If not available, suggest closest time
    2. Always confirm before booking

    # Cancellation Workflow
    1. When user requests to cancel a meeting:
        a. IMMEDIATELY use the cancel_event tool with the provided time and date
        b. Do NOT list all events first unless specifically asked
        c. If multiple events exist at that time, cancel the first matching one
        d. Give clear confirmation or error message
    2. Never show raw API responses to users
    3. For cancellations, always confirm whether it succeeded or failed
    4. If cancellation fails, then list events to help user identify the correct one

    # Important Directives
    - For cancellations, act immediately without unnecessary steps
    - When user gives exact time and date for cancellation, proceed directly to cancel
    - Only list events if the cancellation fails or user asks to see them

    # Rescheduling Workflow
    1. When user requests to reschedule a meeting:
        a. IMMEDIATELY check for meetings at the specified original time and date
        b. Can handle:
            - Same day rescheduling ("move 2pm to 3pm")
            - Different day rescheduling ("move today's 2pm to tomorrow 3pm")
        c. If exactly one meeting found:
            - Confirm details with user
            - Proceed with rescheduling
        d. If no meeting found:
            - Inform user specifically
        e. If multiple meetings found:
            - List just those meetings
            - Ask user to specify which one

    # Schedule Listing Workflow
    1. When user asks to see their schedule/events/meetings:
        a. IMMEDIATELY use the list_scheduled_events tool
        b. Display the results in a clean, readable format
        c. If no events found, suggest booking a new one


""")

    if not state["messages"]:
        initial_message = "Hello! I'm CalBot, your calendar assistant. How can I help?"
        return {"messages": [HumanMessage(content=initial_message), AIMessage(content=initial_message)]}
    
    user_input = input("\n💬 You: ")
    print(f"\n👤 USER: {user_input}")
    user_message = HumanMessage(content=user_input)

    all_messages = [system_prompt] + list(state["messages"]) + [user_message]
    response = model.invoke(all_messages)

    print(f"\n🤖 CalBot: {response.content}")

    return {"messages": list(state["messages"]) + [user_message, response]}





def should_continue(state: AgentState) -> str:
    """Determine if we should continue or end the conversation."""
    messages = state["messages"]
    
    if not messages:
        return "continue"
    
    last_human_message = None
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            last_human_message = message
            break
    
    if last_human_message and any(word in last_human_message.content.lower() for word in ['bye', 'exit', 'quit', 'goodbye']):
        return "end"
        
    return "continue"

def print_messages(messages):
    """Print tool results in a readable format"""
    if not messages:
        return
    
    for message in messages[-2:]:
        if isinstance(message, ToolMessage):
            # Skip printing the full list of events
            if "Your scheduled events:" in message.content:
                continue
            # Clean up cancellation messages
            elif "Error cancelling meeting:" in message.content:
                print(f"\n❌ {message.content.split(':')[-1].strip()}")
            elif "✅" in message.content or "already cancelled" in message.content:
                print(f"\n🤖 {message.content}")
            else:
                print(f"\n🛠️ {message.content}")





# Build the graph
graph = StateGraph(AgentState)

graph.add_node("agent", our_agent)
graph.add_node("tools", ToolNode(tools))

graph.set_entry_point("agent")
graph.add_edge("agent", "tools")

graph.add_conditional_edges(
    "tools",
    should_continue,
    {
        "continue": "agent", 
        "end": END,
    },
)

app = graph.compile()

def run_calcom_agent():
    print("\n🗓️  ===== CALBOT - Your AI Calendar Assistant =====")
    print("💡 I can help you manage your Cal.com calendar!")
    print("📝 Try saying things like:")
    print("   • 'Book a meeting for tomorrow at 2pm'")
    print("   • 'Show me my scheduled events'") 
    print("   • 'Cancel my 3pm meeting today'")
    print("   • 'Reschedule my meeting to next week'")
    print("=" * 50)
    
    state = {"messages": []}
    
    try:
        for step in app.stream(state, stream_mode="values"):
            if "messages" in step:
                print_messages(step["messages"])
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye! Thanks for using CalBot!")
    except Exception as e:
        print(f"\n❌ An error occurred: {str(e)}")
    
    print("\n🗓️  ===== CALBOT SESSION ENDED =====")

if __name__ == "__main__":
    # Check if API keys are set
    if not CALCOM_API_KEY:
        print("❌ Error: CALCOM_API_KEY not found in environment variables")
        print("Please add CALCOM_API_KEY=your_api_key to your .env file")
        exit(1)
    
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ Error: OPENAI_API_KEY not found in environment variables") 
        print("Please add OPENAI_API_KEY=your_api_key to your .env file")
        exit(1)
        
    run_calcom_agent()