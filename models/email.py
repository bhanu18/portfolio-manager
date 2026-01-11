from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional


class EmailRequest(BaseModel):
    """Request model for sending emails"""

    to: List[EmailStr] = Field(..., description="List of recipient email addresses")
    subject: str = Field(..., min_length=1, max_length=200, description="Email subject")
    body: str = Field(..., min_length=1, description="Plain text email body")
    html_body: Optional[str] = Field(None, description="Optional HTML email body")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "to": ["user@example.com"],
                    "subject": "Portfolio Update",
                    "body": "Your portfolio performance this month...",
                    "html_body": "<h1>Portfolio Update</h1><p>Your portfolio performance this month...</p>",
                }
            ]
        }
    }


class EmailResponse(BaseModel):
    """Response model for email sending"""

    success: bool
    message: str
    recipients: List[str]
