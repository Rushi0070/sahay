"""
Gmail Email Fetcher for Job Application Tracking
=================================================

This module handles all Gmail-related functionality:
    1. Authentication with Google OAuth (via Supabase)
    2. Fetching emails from Gmail API
    3. Extracting email content (headers, body, attachments)
    4. Formatting emails for LLM processing
    5. Saving job applications to Supabase database

The main classes are:
    - GmailAuthenticator: Handles OAuth flow and token management
    - GmailFetcher: Fetches and processes emails from Gmail
    - JobApplicationTracker: Saves applications to Supabase

Usage (standalone):
    python fetch_emails.py
    
Usage (as module):
    from fetch_emails import GmailFetcher, JobApplicationTracker
"""

# =============================================================================
# IMPORTS
# =============================================================================

import os
import re
import base64
import webbrowser
from html import unescape
from dataclasses import dataclass
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode

import httpx
from supabase import create_client, Client
from dotenv import load_dotenv

from llm_evoke import extract_email_info_using_gemini

# Load environment variables from .env file
load_dotenv()


# =============================================================================
# DATA CLASS
# =============================================================================

@dataclass
class ExtractedEmail:
    """
    Container for email data that has been processed for LLM consumption.
    
    This dataclass holds all the relevant parts of an email after extraction
    from the raw Gmail API response. It separates the email into easily 
    accessible components.
    
    Attributes:
        id: Unique Gmail message ID
        thread_id: ID of the email thread this message belongs to
        labels: List of Gmail labels (e.g., "INBOX", "UNREAD")
        snippet: Short preview of the email content
        headers: Dictionary of email headers (From, To, Subject, Date, etc.)
        body_text: The best available text representation of the email body
        body_plain: Plain text version of the body (if available)
        body_html: HTML version of the body (if available)
        attachments: List of attachment metadata (filename, size, mime type)
        inline_images: List of inline image metadata
    """
    id: str
    thread_id: str
    labels: list
    snippet: str
    headers: dict
    body_text: str
    body_plain: str
    body_html: str
    attachments: list
    inline_images: list


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def decode_base64_content(encoded_data: str) -> str:
    """
    Decode base64-encoded email content from Gmail.
    
    Gmail API returns email body content in base64url encoding. This function
    handles the decoding process safely, returning an empty string if decoding
    fails for any reason.
    
    Args:
        encoded_data: The base64url-encoded string from Gmail API
        
    Returns:
        Decoded string content, or empty string if decoding fails
    """
    try:
        # Gmail uses URL-safe base64 encoding
        decoded_bytes = base64.urlsafe_b64decode(encoded_data)
        return decoded_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return ""


def convert_html_to_plain_text(html_content: str) -> str:
    """
    Convert HTML email content to plain text.
    
    Many emails are HTML-only. This function strips out HTML tags, scripts,
    and styles to produce readable plain text. It also converts HTML entities
    to their character equivalents.
    
    Args:
        html_content: Raw HTML string from the email body
        
    Returns:
        Clean plain text with HTML tags and scripts removed
    """
    # Step 1: Remove style blocks (CSS that would clutter the output)
    text = re.sub(
        r'<style[^>]*>.*?</style>', 
        '', 
        html_content, 
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Step 2: Remove script blocks (JavaScript)
    text = re.sub(
        r'<script[^>]*>.*?</script>', 
        '', 
        text, 
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Step 3: Remove all remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Step 4: Convert HTML entities (e.g., &amp; -> &, &nbsp; -> space)
    text = unescape(text)
    
    # Step 5: Clean up excessive whitespace
    text = re.sub(r'\s+', ' ', text)  # Multiple spaces to single space
    text = re.sub(r'\n\s*\n', '\n\n', text)  # Normalize blank lines
    
    return text.strip()


# =============================================================================
# EMAIL EXTRACTION
# =============================================================================

def extract_email_content(raw_gmail_response: dict) -> ExtractedEmail:
    """
    Extract useful content from a raw Gmail API response.
    
    The Gmail API returns emails in a complex nested structure with MIME parts.
    This function recursively processes all parts to extract the plain text body,
    HTML body, and any attachments.
    
    Args:
        raw_gmail_response: The raw JSON response from Gmail API messages.get()
        
    Returns:
        ExtractedEmail object with all content properly extracted
    """
    # Initialize containers for extracted content
    headers = {}
    body_plain = None
    body_html = None
    attachments = []
    inline_images = []
    
    # Extract basic metadata from the response
    email_id = raw_gmail_response.get("id", "")
    thread_id = raw_gmail_response.get("threadId", "")
    labels = raw_gmail_response.get("labelIds", [])
    snippet = raw_gmail_response.get("snippet", "")
    
    # Get the payload which contains headers and body parts
    payload = raw_gmail_response.get("payload", {})
    raw_headers = payload.get("headers", [])
    
    # Extract only the headers we care about for job applications
    # These are the most useful for understanding email context
    useful_headers = ["From", "To", "Cc", "Bcc", "Subject", "Date", "Reply-To"]
    for header in raw_headers:
        if header["name"] in useful_headers:
            headers[header["name"]] = header["value"]
    
    # Define a recursive function to process MIME parts
    # Emails can have deeply nested multipart structures
    def process_mime_part(part: dict):
        """Process a single MIME part and its nested children."""
        nonlocal body_plain, body_html, attachments, inline_images
        
        mime_type = part.get("mimeType", "")
        filename = part.get("filename", "")
        body_data = part.get("body", {})
        
        # Check if this part is an attachment (has a filename)
        if filename:
            attachment_info = {
                "filename": filename,
                "mime_type": mime_type,
                "size": body_data.get("size", 0),
                "attachment_id": body_data.get("attachmentId", ""),
            }
            
            # Separate large images (likely inline) from regular attachments
            is_image = mime_type.startswith("image/")
            is_large = body_data.get("size", 0) > 5000
            
            if is_image and is_large:
                inline_images.append(attachment_info)
            else:
                attachments.append(attachment_info)
        
        # Check if this part has body content (no filename, has data)
        elif body_data.get("data"):
            decoded = decode_base64_content(body_data["data"])
            
            # Store plain text and HTML versions separately
            if mime_type == "text/plain":
                body_plain = decoded
            elif mime_type == "text/html":
                body_html = decoded
        
        # Recursively process any nested parts (multipart emails)
        for sub_part in part.get("parts", []):
            process_mime_part(sub_part)
    
    # Start processing from the top-level payload
    process_mime_part(payload)
    
    # Determine the best body text to use
    # Prefer plain text, fall back to converted HTML, then snippet
    if body_plain:
        body_text = body_plain
    elif body_html:
        body_text = convert_html_to_plain_text(body_html)
    else:
        body_text = snippet
    
    return ExtractedEmail(
        id=email_id,
        thread_id=thread_id,
        labels=labels,
        snippet=snippet,
        headers=headers,
        body_text=body_text,
        body_plain=body_plain or "",
        body_html=body_html or "",
        attachments=attachments,
        inline_images=inline_images,
    )


def format_email_for_llm(email: ExtractedEmail) -> str:
    """
    Format an extracted email as clean text for LLM processing.
    
    This creates a structured text representation of the email that is
    easy for LLMs to parse and understand. The format includes clear
    section headers and organized metadata.
    
    Args:
        email: An ExtractedEmail object to format
        
    Returns:
        A formatted string suitable for sending to an LLM
    """
    lines = []
    
    # Header section
    lines.append("=" * 50)
    lines.append("EMAIL CONTENT")
    lines.append("=" * 50)
    lines.append("")
    
    # Metadata section - key headers for understanding context
    lines.append("--- METADATA ---")
    for key in ["From", "To", "Cc", "Date", "Subject"]:
        if key in email.headers:
            lines.append(f"{key}: {email.headers[key]}")
    lines.append(f"Labels: {', '.join(email.labels)}")
    lines.append("")
    
    # Body section - the main email content
    lines.append("--- BODY ---")
    lines.append(email.body_text if email.body_text else "(No body content)")
    lines.append("")
    
    # Attachments section (if any)
    if email.attachments:
        lines.append("--- ATTACHMENTS ---")
        for att in email.attachments:
            size_kb = att["size"] / 1024
            lines.append(f"- {att['filename']} ({att['mime_type']}, {size_kb:.1f} KB)")
        lines.append("")
    
    # Images section (if any)
    if email.inline_images:
        lines.append("--- IMAGES ---")
        for img in email.inline_images:
            size_kb = img["size"] / 1024
            lines.append(f"- {img['filename']} ({img['mime_type']}, {size_kb:.1f} KB)")
        lines.append("")
    
    lines.append("=" * 50)
    
    return "\n".join(lines)


# =============================================================================
# GMAIL AUTHENTICATION
# =============================================================================

class GmailAuthenticator:
    """
    Handles Gmail authentication through Supabase OAuth.
    
    This class manages the OAuth flow for getting a Google access token
    that has permission to read Gmail. It handles:
        - Loading saved tokens from disk
        - Validating token expiration
        - Running the OAuth flow via browser
        - Saving tokens for reuse
    
    The authentication flow works by:
        1. Opening a browser to Google's OAuth consent screen
        2. Starting a local HTTP server to receive the callback
        3. Extracting the provider_token from the callback URL
        4. Saving the token for future use
    
    Attributes:
        token_file: Path to file where token is stored
        access_token: Current access token (if authenticated)
    """
    
    def __init__(self, token_file: str = "gmail_token.txt"):
        """
        Initialize the authenticator.
        
        Args:
            token_file: Path to store/load the access token
        """
        self.token_file = token_file
        self.access_token: Optional[str] = None
    
    def get_oauth_url(self) -> str:
        """
        Generate the OAuth login URL for Supabase Google auth.
        
        This constructs the URL that will redirect users to Google's
        consent screen with the correct scopes for Gmail access.
        
        Returns:
            Full OAuth URL to open in browser
        """
        params = {
            'provider': 'google',
            'redirect_to': 'http://localhost:3000',
            'scopes': 'email https://www.googleapis.com/auth/gmail.readonly'
        }
        supabase_url = os.getenv('SUPABASE_URL')
        return f"{supabase_url}/auth/v1/authorize?{urlencode(params)}"
    
    def is_token_valid(self, token: str) -> bool:
        """
        Check if a token is still valid by calling Google's tokeninfo endpoint.
        
        Args:
            token: The access token to validate
            
        Returns:
            True if token is valid, False otherwise
        """
        try:
            response = httpx.get(
                'https://www.googleapis.com/oauth2/v1/tokeninfo',
                params={'access_token': token},
                timeout=10.0
            )
            return response.status_code == 200
        except httpx.RequestError:
            return False
    
    def load_saved_token(self) -> Optional[str]:
        """
        Load and validate a previously saved token.
        
        Checks if a token file exists, reads it, and validates that
        the token is still valid with Google.
        
        Returns:
            Valid token string, or None if no valid token exists
        """
        if not os.path.exists(self.token_file):
            return None
        
        with open(self.token_file, 'r') as f:
            token = f.read().strip()
        
        if token and self.is_token_valid(token):
            return token
        
        print("Saved token expired or invalid.")
        return None
    
    def save_token(self, token: str):
        """
        Save a token to the token file.
        
        Args:
            token: The access token to save
        """
        with open(self.token_file, 'w') as f:
            f.write(token)
    
    def run_oauth_flow(self) -> str:
        """
        Run the full OAuth flow: open browser, wait for callback, return token.
        
        This method:
            1. Opens the user's browser to Google's consent page
            2. Starts a local HTTP server on port 3000
            3. Waits for Google to redirect back with the token
            4. Extracts and returns the provider_token
        
        Returns:
            The Google access token from the OAuth flow
        """
        captured_token = None
        
        class OAuthCallbackHandler(BaseHTTPRequestHandler):
            """HTTP handler to receive the OAuth callback."""
            
            def do_GET(self):
                """Handle the GET request from OAuth redirect."""
                nonlocal captured_token
                
                # Parse the query parameters from the callback URL
                query_string = urlparse(self.path).query
                params = parse_qs(query_string)
                
                if 'provider_token' in params:
                    # Token received! Send success page and store token
                    captured_token = params['provider_token'][0]
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b'''
                        <html><body style="font-family: system-ui; display: flex; 
                            justify-content: center; align-items: center; 
                            height: 100vh; margin: 0; background: #0f172a;">
                            <div style="text-align: center; color: white;">
                                <h1 style="color: #22c55e;">Success!</h1>
                                <p>You can close this window.</p>
                            </div>
                        </body></html>
                    ''')
                else:
                    # No token yet - send page with JS to extract from hash
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b'''
                        <html><body style="font-family: system-ui; display: flex; 
                            justify-content: center; align-items: center; 
                            height: 100vh; margin: 0; background: #0f172a;">
                            <div style="text-align: center; color: white;">
                                <h2>Processing login...</h2>
                            </div>
                            <script>
                                const hash = window.location.hash.substring(1);
                                const params = new URLSearchParams(hash);
                                const token = params.get('provider_token');
                                if (token) {
                                    window.location.href = 'http://localhost:3000/callback?provider_token=' + token;
                                }
                            </script>
                        </body></html>
                    ''')
            
            def log_message(self, format, *args):
                """Suppress default HTTP server logging."""
                pass
        
        # Open browser and wait for callback
        print("Opening browser for Google sign-in...")
        webbrowser.open(self.get_oauth_url())
        
        # Start local server to receive the callback
        server = HTTPServer(('localhost', 3000), OAuthCallbackHandler)
        while captured_token is None:
            server.handle_request()
        server.server_close()
        
        return captured_token
    
    def authenticate(self) -> str:
        """
        Get a valid access token, either from cache or by logging in.
        
        This is the main entry point for authentication. It first tries
        to use a saved token, and only runs the OAuth flow if necessary.
        
        Returns:
            A valid Google access token
        """
        # Try to use saved token first
        saved_token = self.load_saved_token()
        if saved_token:
            print("Using saved authentication token.")
            self.access_token = saved_token
            return saved_token
        
        # No valid saved token - need to login
        print("No valid saved token. Starting login flow...")
        new_token = self.run_oauth_flow()
        
        # Save for next time
        self.save_token(new_token)
        print("Login successful! Token saved.")
        
        self.access_token = new_token
        return new_token


# =============================================================================
# GMAIL FETCHER
# =============================================================================

class GmailFetcher:
    """
    Fetches emails from Gmail API.
    
    This class handles all communication with the Gmail API to fetch
    email lists and individual email details. It uses the access token
    from GmailAuthenticator.
    
    Attributes:
        GMAIL_API_BASE: Base URL for Gmail API endpoints
        access_token: Google access token with Gmail scope
        headers: HTTP headers including Authorization
    """
    
    GMAIL_API_BASE = "https://www.googleapis.com/gmail/v1/users/me"
    
    def __init__(self, access_token: str):
        """
        Initialize the fetcher with an access token.
        
        Args:
            access_token: Valid Google access token with Gmail read scope
        """
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}
    
    def fetch_email_list(self, query: str = "in:inbox", max_results: int = 10) -> list[dict]:
        """
        Get a list of email IDs matching a search query.
        
        Args:
            query: Gmail search query (same syntax as Gmail search box)
                   Examples: "in:inbox", "from:company.com", "subject:application"
            max_results: Maximum number of emails to return (1-500)
            
        Returns:
            List of dicts with 'id' and 'threadId' keys
        """
        url = f"{self.GMAIL_API_BASE}/messages"
        params = {"maxResults": max_results, "q": query}
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=self.headers, params=params)
            data = response.json()
            
            if "error" in data:
                print(f"Error fetching emails: {data['error']['message']}")
                return []
            
            return data.get("messages", [])
    
    def fetch_email_details(self, message_id: str) -> dict:
        """
        Get the full details of a single email by its ID.
        
        Args:
            message_id: The Gmail message ID
            
        Returns:
            Full email data from Gmail API
        """
        url = f"{self.GMAIL_API_BASE}/messages/{message_id}"
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=self.headers, params={"format": "full"})
            return response.json()
    
    def fetch_and_extract_email(self, message_id: str) -> ExtractedEmail:
        """
        Fetch an email and extract it for processing.
        
        Combines fetch_email_details and extract_email_content into
        a single convenient method.
        
        Args:
            message_id: The Gmail message ID
            
        Returns:
            ExtractedEmail object ready for LLM processing
        """
        raw_email = self.fetch_email_details(message_id)
        return extract_email_content(raw_email)
    
    def fetch_latest_email_for_llm(self, query: str = "in:inbox") -> tuple[ExtractedEmail, str]:
        """
        Fetch the most recent email and format it for LLM processing.
        
        This is a convenience method that fetches the latest email matching
        a query and returns both the extracted email and its LLM-formatted text.
        
        Args:
            query: Gmail search query
            
        Returns:
            Tuple of (ExtractedEmail, formatted_string)
            
        Raises:
            ValueError: If no emails match the query
        """
        messages = self.fetch_email_list(query=query, max_results=1)
        
        if not messages:
            raise ValueError("No emails found matching query")
        
        extracted = self.fetch_and_extract_email(messages[0]["id"])
        formatted = format_email_for_llm(extracted)
        
        return extracted, formatted


# =============================================================================
# JOB APPLICATION TRACKER
# =============================================================================

class JobApplicationTracker:
    """
    Saves job applications to Supabase database.
    
    This class handles the database operations for tracking job applications.
    It uses the LLM to classify emails and extract relevant information before
    saving to Supabase.
    
    The workflow is:
        1. Check if email was already processed (by Gmail ID)
        2. Send email to LLM for classification
        3. If it's a job email, extract company/title/status
        4. Save to Supabase 'active_applications' table
    
    Attributes:
        supabase: Supabase client instance
    """
    
    def __init__(self):
        """Initialize the tracker with Supabase client."""
        self.supabase: Client = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_KEY')
        )
    
    def save_application(self, email: ExtractedEmail) -> bool:
        """
        Save a job application to the database using LLM extraction.
        
        This method:
            1. Checks if this email was already processed
            2. Uses the LLM to classify and extract information
            3. Only saves if it's a job application email
        
        Args:
            email: ExtractedEmail object to process
            
        Returns:
            True if saved successfully, False if skipped/duplicate
        """
        gmail_id = email.id
        
        # Step 1: Check if this email was already processed
        existing = self.supabase.table('active_applications').select('email_id').eq('email_id', gmail_id).execute()
        
        if existing.data:
            print(f"- Already processed: Email ID {gmail_id[:20]}...")
            return False
        
        # Step 2: Classify and extract using LLM
        result = extract_email_info_using_gemini(email.body_text)
        
        # Step 3: Check if LLM classified this as a job application
        if not result.get('is_job_application', False):
            reason = result.get('reasoning', 'Not classified as job application')
            print(f"- Skipped: {reason}")
            return False
        
        company_name = result['company_name']
        job_title = result['job_title']
        
        # Step 4: Save to database
        try:
            self.supabase.table('active_applications').insert({
                'company_name': result['company_name'],
                'job_title': result['job_title'],
                'status': result['status'],
                'email_id': gmail_id
            }).execute()
            
            print(f"+ Saved: {company_name} - {job_title or 'Unknown Position'}")
            return True
            
        except Exception as e:
            # Handle duplicate key errors gracefully
            if 'duplicate' in str(e).lower() or '23505' in str(e):
                print(f"- Already tracked: {company_name}")
                return False
            raise
    
    def get_all_applications(self) -> list[dict]:
        """
        Get all tracked applications from the database.
        
        Returns:
            List of application records as dictionaries
        """
        result = self.supabase.table('active_applications').select('*').execute()
        return result.data


# =============================================================================
# MAIN - Standalone script execution
# =============================================================================

def main():
    """
    Main entry point for standalone script execution.
    
    This function demonstrates the full workflow:
        1. Authenticate with Gmail
        2. Fetch the latest email
        3. Display the email content
        4. Save to Supabase if it's a job application
    """
    print("=" * 60)
    print("  Gmail Job Application Tracker")
    print("=" * 60)
    print()
    
    # Step 1: Authenticate with Gmail
    print("Step 1: Authenticating with Gmail...")
    auth = GmailAuthenticator()
    token = auth.authenticate()
    print()
    
    # Step 2: Fetch the latest email
    print("Step 2: Fetching most recent email...")
    fetcher = GmailFetcher(access_token=token)
    
    try:
        extracted_email, llm_formatted = fetcher.fetch_latest_email_for_llm(query="in:inbox")
    except ValueError as e:
        print(f"Error: {e}")
        return
    print()
    
    # Step 3: Display email content
    print("Step 3: Email content:")
    print()
    print(llm_formatted)
    print()
    
    # Step 4: Save to Supabase (if it's a job application)
    print("Step 4: Processing with LLM and saving...")
    tracker = JobApplicationTracker()
    tracker.save_application(extracted_email)
    
    print()
    print("=" * 60)
    print("  Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
