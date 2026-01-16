"""
Gmail Email Fetcher for Job Application Tracking
=================================================

This script:
1. Authenticates with Gmail using Google OAuth (via Supabase)
2. Fetches emails from your inbox
3. Extracts useful content (headers, body, attachments)
4. Formats the email for LLM processing
5. Saves job applications to a Supabase database
"""

# =============================================================================
# IMPORTS
# =============================================================================

import os
import re
import base64
import json
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

load_dotenv()


# =============================================================================
# DATA CLASS
# =============================================================================

@dataclass
class ExtractedEmail:
    """Container for email data processed for LLM consumption."""
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
    """Decode base64-encoded email content from Gmail."""
    try:
        decoded_bytes = base64.urlsafe_b64decode(encoded_data)
        return decoded_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return ""


def convert_html_to_plain_text(html_content: str) -> str:
    """Convert HTML content to plain text by removing tags and scripts."""
    # Remove style and script tags
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Convert HTML entities
    text = unescape(text)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    return text.strip()


# =============================================================================
# EMAIL EXTRACTION
# =============================================================================

def extract_email_content(raw_gmail_response: dict) -> ExtractedEmail:
    """Extract useful content from a raw Gmail API response."""
    headers = {}
    body_plain = None
    body_html = None
    attachments = []
    inline_images = []
    
    # Basic info
    email_id = raw_gmail_response.get("id", "")
    thread_id = raw_gmail_response.get("threadId", "")
    labels = raw_gmail_response.get("labelIds", [])
    snippet = raw_gmail_response.get("snippet", "")
    
    # Extract headers
    payload = raw_gmail_response.get("payload", {})
    raw_headers = payload.get("headers", [])
    
    useful_headers = ["From", "To", "Cc", "Bcc", "Subject", "Date", "Reply-To"]
    for header in raw_headers:
        if header["name"] in useful_headers:
            headers[header["name"]] = header["value"]
    
    # Process MIME parts recursively
    def process_mime_part(part: dict):
        nonlocal body_plain, body_html, attachments, inline_images
        
        mime_type = part.get("mimeType", "")
        filename = part.get("filename", "")
        body_data = part.get("body", {})
        
        if filename:
            # It's an attachment
            attachment_info = {
                "filename": filename,
                "mime_type": mime_type,
                "size": body_data.get("size", 0),
                "attachment_id": body_data.get("attachmentId", ""),
            }
            
            is_image = mime_type.startswith("image/")
            is_large = body_data.get("size", 0) > 5000
            
            if is_image and is_large:
                inline_images.append(attachment_info)
            else:
                attachments.append(attachment_info)
        
        elif body_data.get("data"):
            # It's body content
            decoded = decode_base64_content(body_data["data"])
            if mime_type == "text/plain":
                body_plain = decoded
            elif mime_type == "text/html":
                body_html = decoded
        
        # Process nested parts
        for sub_part in part.get("parts", []):
            process_mime_part(sub_part)
    
    process_mime_part(payload)
    
    # Determine best body text
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
    """Format an extracted email as clean text for LLM processing."""
    lines = []
    
    lines.append("=" * 50)
    lines.append("EMAIL CONTENT")
    lines.append("=" * 50)
    lines.append("")
    
    # Metadata
    lines.append("--- METADATA ---")
    for key in ["From", "To", "Cc", "Date", "Subject"]:
        if key in email.headers:
            lines.append(f"{key}: {email.headers[key]}")
    lines.append(f"Labels: {', '.join(email.labels)}")
    lines.append("")
    
    # Body
    lines.append("--- BODY ---")
    lines.append(email.body_text if email.body_text else "(No body content)")
    lines.append("")
    
    # Attachments
    if email.attachments:
        lines.append("--- ATTACHMENTS ---")
        for att in email.attachments:
            size_kb = att["size"] / 1024
            lines.append(f"• {att['filename']} ({att['mime_type']}, {size_kb:.1f} KB)")
        lines.append("")
    
    # Images
    if email.inline_images:
        lines.append("--- IMAGES ---")
        for img in email.inline_images:
            size_kb = img["size"] / 1024
            lines.append(f"• {img['filename']} ({img['mime_type']}, {size_kb:.1f} KB)")
        lines.append("")
    
    lines.append("=" * 50)
    
    return "\n".join(lines)


# =============================================================================
# GMAIL AUTHENTICATION
# =============================================================================

class GmailAuthenticator:
    """Handles Gmail authentication through Supabase OAuth."""
    
    def __init__(self, token_file: str = "gmail_token.txt"):
        self.token_file = token_file
        self.access_token: Optional[str] = None
    
    def get_oauth_url(self) -> str:
        """Generate the OAuth login URL."""
        params = {
            'provider': 'google',
            'redirect_to': 'http://localhost:3000',
            'scopes': 'email https://www.googleapis.com/auth/gmail.readonly'
        }
        supabase_url = os.getenv('SUPABASE_URL')
        return f"{supabase_url}/auth/v1/authorize?{urlencode(params)}"
    
    def is_token_valid(self, token: str) -> bool:
        """Check if token is still valid."""
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
        """Load and validate saved token."""
        if not os.path.exists(self.token_file):
            return None
        
        with open(self.token_file, 'r') as f:
            token = f.read().strip()
        
        if token and self.is_token_valid(token):
            return token
        
        print("Saved token expired or invalid.")
        return None
    
    def save_token(self, token: str):
        """Save token to file."""
        with open(self.token_file, 'w') as f:
            f.write(token)
    
    def run_oauth_flow(self) -> str:
        """Run OAuth flow: open browser, wait for callback, return token."""
        captured_token = None
        
        class OAuthCallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal captured_token
                
                query_string = urlparse(self.path).query
                params = parse_qs(query_string)
                
                if 'provider_token' in params:
                    captured_token = params['provider_token'][0]
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b'''
                        <html><body style="font-family: system-ui; display: flex; 
                            justify-content: center; align-items: center; 
                            height: 100vh; margin: 0; background: #0f172a;">
                            <div style="text-align: center; color: white;">
                                <h1 style="color: #22c55e;">&#10003; Success!</h1>
                                <p>You can close this window.</p>
                            </div>
                        </body></html>
                    ''')
                else:
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
                pass  # Suppress logging
        
        print("Opening browser for Google sign-in...")
        webbrowser.open(self.get_oauth_url())
        
        server = HTTPServer(('localhost', 3000), OAuthCallbackHandler)
        while captured_token is None:
            server.handle_request()
        server.server_close()
        
        return captured_token
    
    def authenticate(self) -> str:
        """Get a valid access token (from cache or by logging in)."""
        saved_token = self.load_saved_token()
        if saved_token:
            print("Using saved authentication token.")
            self.access_token = saved_token
            return saved_token
        
        print("No valid saved token. Starting login flow...")
        new_token = self.run_oauth_flow()
        
        self.save_token(new_token)
        print("Login successful! Token saved.")
        
        self.access_token = new_token
        return new_token


# =============================================================================
# GMAIL FETCHER
# =============================================================================

class GmailFetcher:
    """Fetches emails from Gmail API."""
    
    GMAIL_API_BASE = "https://www.googleapis.com/gmail/v1/users/me"
    
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}
    
    def fetch_email_list(self, query: str = "in:inbox", max_results: int = 10) -> list[dict]:
        """Get list of email IDs matching a search query."""
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
        """Get full details of a single email."""
        url = f"{self.GMAIL_API_BASE}/messages/{message_id}"
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=self.headers, params={"format": "full"})
            return response.json()
    
    def fetch_and_extract_email(self, message_id: str) -> ExtractedEmail:
        """Fetch an email and extract it for LLM processing."""
        raw_email = self.fetch_email_details(message_id)
        return extract_email_content(raw_email)
    
    def fetch_latest_email_for_llm(self, query: str = "in:inbox") -> tuple[ExtractedEmail, str]:
        """Fetch most recent email formatted for LLM."""
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
    """Saves job applications to Supabase database."""
    
    def __init__(self):
        self.supabase: Client = create_client(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_KEY')
        )
    
    def save_application(self, email: ExtractedEmail) -> bool:
        """Save a job application to the database using LLM extraction."""
        gmail_id = email.id  # The actual Gmail message ID
        
        # Step 1: Check if this email was already processed (using email_id column)
        existing = self.supabase.table('active_applications').select('email_id').eq('email_id', gmail_id).execute()
        
        if existing.data:
            print(f"• Already processed: Email ID {gmail_id[:20]}...")
            return False
        
        # Step 2: Classify and extract using LLM
        result = extract_email_info_using_gemini(email.body_text)
        
        # Check if LLM classified this as a job application
        if not result.get('is_job_application', False):
            reason = result.get('reasoning', 'Not classified as job application')
            print(f"⏭️  Not saving: {reason}")
            return False
        
        company_name = result['company_name']
        job_title = result['job_title']
        
        # Step 3: Save to database (store Gmail ID in email_id for deduplication)
        try:
            self.supabase.table('active_applications').insert({
                'company_name': result['company_name'],
                'job_title': result['job_title'],
                'status': result['status'],
                'email_id': gmail_id  # Store actual Gmail message ID here
            }).execute()
            
            print(f"✓ Saved: {company_name} - {job_title or 'Unknown Position'}")
            return True
            
        except Exception as e:
            if 'duplicate' in str(e).lower() or '23505' in str(e):
                print(f"• Already tracked: {company_name}")
                return False
            raise
    
    def get_all_applications(self) -> list[dict]:
        """Get all tracked applications from the database."""
        result = self.supabase.table('active_applications').select('*').execute()
        return result.data


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Fetch latest email and save to Supabase."""
    print("=" * 60)
    print("  Gmail Job Application Tracker")
    print("=" * 60)
    print()
    
    # Step 1: Authenticate
    print("Step 1: Authenticating with Gmail...")
    auth = GmailAuthenticator()
    token = auth.authenticate()
    print()
    
    # Step 2: Fetch email
    print("Step 2: Fetching most recent email...")
    fetcher = GmailFetcher(access_token=token)
    
    try:
        extracted_email, llm_formatted = fetcher.fetch_latest_email_for_llm(query="in:inbox")
    except ValueError as e:
        print(f"Error: {e}")
        return
    print()
    
    # Step 3: Display email
    print("Step 3: Email content:")
    print()
    print(llm_formatted)
    print()
    
    # Step 4: Save files
    print("Step 4: Saving files...")
    with open("email_for_llm.txt", "w", encoding="utf-8") as f:
        f.write(llm_formatted)
    print("  • email_for_llm.txt saved")
    print()
    
    # Step 5: Save to Supabase
    print("Step 5: Saving to Supabase...")
    tracker = JobApplicationTracker()
    tracker.save_application(extracted_email)
    
    print()
    print("=" * 60)
    print("  Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
