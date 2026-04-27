import logging
import io
import pandas as pd
from typing import List, Dict, Any, Optional
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from app.core.config import settings

logger = logging.getLogger(__name__)

# Scopes required for the application
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

class GoogleDriveService:
    def __init__(self):
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.redirect_uri = settings.GOOGLE_REDIRECT_URI

    def get_flow(self):
        return Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=SCOPES
        )

    def get_authorization_url(self) -> str:
        """Generates the authorization URL for Google OAuth."""
        if not self.client_id or not self.client_secret:
            logger.warning("Google Drive credentials not configured.")
            return ""
        
        flow = self.get_flow()
        flow.redirect_uri = self.redirect_uri
        auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
        return auth_url

    def get_credentials(self, code: str) -> Dict[str, Any]:
        """Exchanges the authorization code for credentials."""
        flow = self.get_flow()
        flow.redirect_uri = self.redirect_uri
        flow.fetch_token(code=code)
        creds = flow.credentials
        return {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }

    def list_files(self, creds_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Lists CSV and Google Sheets files from Drive."""
        creds = Credentials(**creds_dict)
        service = build('drive', 'v3', credentials=creds)
        
        # Query for CSV files and Google Sheets
        query = "mimeType = 'text/csv' or mimeType = 'application/vnd.google-apps.spreadsheet'"
        results = service.files().list(
            q=query, 
            pageSize=50, 
            fields="nextPageToken, files(id, name, mimeType, modifiedTime)"
        ).execute()
        
        return results.get('files', [])

    def download_file(self, file_id: str, creds_dict: Dict[str, Any]) -> pd.DataFrame:
        """Downloads a file and returns it as a pandas DataFrame."""
        creds = Credentials(**creds_dict)
        service = build('drive', 'v3', credentials=creds)
        
        # Get file metadata to check mimeType
        file_metadata = service.files().get(fileId=file_id).execute()
        mime_type = file_metadata.get('mimeType')
        name = file_metadata.get('name')

        request = None
        if mime_type == 'application/vnd.google-apps.spreadsheet':
            # Export Google Sheets to CSV
            request = service.files().export_media(fileId=file_id, mimeType='text/csv')
        else:
            # Download regular files (CSV)
            request = service.files().get_media(fileId=file_id)

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        fh.seek(0)
        try:
            df = pd.read_csv(fh)
            return df
        except Exception as e:
            logger.error(f"Failed to parse downloaded file as CSV: {e}")
            raise ValueError(f"Selected file '{name}' is not a valid CSV or readable spreadsheet.")

drive_service = GoogleDriveService()
