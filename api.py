"""
FastAPI Backend for SyncApply
=============================

Exposes REST API endpoints for the frontend to:
- Authenticate via Supabase/Google OAuth
- Fetch and process emails
- Save job applications to database
"""

import os
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import httpx
from dotenv import load_dotenv

from fetch_emails import (
    GmailFetcher, 
    JobApplicationTracker, 
    extract_email_content, 
    format_email_for_llm,
    ExtractedEmail
)

# Debug file path
DEBUG_EMAIL_FILE = "email_for_llm.txt"


def save_email_for_debugging(email: ExtractedEmail):
    """Save email content to file for debugging purposes."""
    formatted = format_email_for_llm(email)
    with open(DEBUG_EMAIL_FILE, "w", encoding="utf-8") as f:
        f.write(formatted)
    print(f"📧 Debug: Saved email to {DEBUG_EMAIL_FILE}")

load_dotenv()

app = FastAPI(
    title="SyncApply API",
    description="Gmail Job Application Tracker API",
    version="1.0.0"
)

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# MODELS
# =============================================================================

class EmailResponse(BaseModel):
    id: str
    subject: Optional[str]
    sender: Optional[str]
    date: Optional[str]
    snippet: str
    body_text: str


class ApplicationResponse(BaseModel):
    company_name: Optional[str]
    job_title: Optional[str]
    status: Optional[str]
    email_id: Optional[str]


class SaveResult(BaseModel):
    success: bool
    message: str
    data: Optional[ApplicationResponse] = None


# =============================================================================
# HELPERS
# =============================================================================

async def verify_google_token(authorization: str = Header(...)) -> str:
    """Verify the Google OAuth token from the Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization.replace("Bearer ", "")
    
    # Verify token with Google
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://www.googleapis.com/oauth2/v1/tokeninfo",
            params={"access_token": token}
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return token


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "SyncApply API"}


@app.get("/api/emails", response_model=list[EmailResponse])
async def get_emails(
    query: str = "in:inbox",
    max_results: int = 10,
    token: str = Depends(verify_google_token)
):
    """
    Fetch emails from Gmail.
    
    Query examples:
    - "in:inbox" - All inbox emails
    - "from:company.com" - Emails from specific domain
    - "subject:application" - Emails with 'application' in subject
    """
    try:
        fetcher = GmailFetcher(access_token=token)
        messages = fetcher.fetch_email_list(query=query, max_results=max_results)
        
        emails = []
        for msg in messages:
            extracted = fetcher.fetch_and_extract_email(msg["id"])
            emails.append(EmailResponse(
                id=extracted.id,
                subject=extracted.headers.get("Subject"),
                sender=extracted.headers.get("From"),
                date=extracted.headers.get("Date"),
                snippet=extracted.snippet,
                body_text=extracted.body_text
            ))
        
        return emails
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/emails/{email_id}", response_model=EmailResponse)
async def get_email(
    email_id: str,
    token: str = Depends(verify_google_token)
):
    """Fetch a single email by ID."""
    try:
        fetcher = GmailFetcher(access_token=token)
        extracted = fetcher.fetch_and_extract_email(email_id)
        
        return EmailResponse(
            id=extracted.id,
            subject=extracted.headers.get("Subject"),
            sender=extracted.headers.get("From"),
            date=extracted.headers.get("Date"),
            snippet=extracted.snippet,
            body_text=extracted.body_text
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/applications/save/{email_id}", response_model=SaveResult)
async def save_application(
    email_id: str,
    token: str = Depends(verify_google_token)
):
    """
    Process an email and save the job application to Supabase.
    Uses LLM to extract company name, job title, and status.
    """
    try:
        # Fetch the email
        fetcher = GmailFetcher(access_token=token)
        extracted = fetcher.fetch_and_extract_email(email_id)
        
        # Save to debug file
        save_email_for_debugging(extracted)
        
        # Save to database (uses LLM extraction internally)
        tracker = JobApplicationTracker()
        success = tracker.save_application(extracted)
        
        if success:
            return SaveResult(
                success=True,
                message="Application saved successfully"
            )
        else:
            return SaveResult(
                success=False,
                message="Application already exists in database"
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/applications", response_model=list[dict])
async def get_applications():
    """Get all saved job applications from the database."""
    try:
        tracker = JobApplicationTracker()
        applications = tracker.get_all_applications()
        return applications
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/applications/process-latest", response_model=SaveResult)
async def process_latest_email(
    query: str = "in:inbox",
    token: str = Depends(verify_google_token)
):
    """
    Fetch the latest email matching query and save as application.
    This is a convenience endpoint for quick processing.
    """
    try:
        fetcher = GmailFetcher(access_token=token)
        extracted, _ = fetcher.fetch_latest_email_for_llm(query=query)
        
        # Save to debug file
        save_email_for_debugging(extracted)
        
        tracker = JobApplicationTracker()
        success = tracker.save_application(extracted)
        
        return SaveResult(
            success=success,
            message="Processed latest email" if success else "Already tracked"
        )
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RUN SERVER
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    print("Starting SyncApply API server...")
    print("Docs available at: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
