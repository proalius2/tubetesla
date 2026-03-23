"""
YouTube Service Module

Handles extraction of video/audio URLs from YouTube using yt-dlp.
Provides methods for stream info extraction and video search.
"""

import yt_dlp
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class StreamInfo:
    """Data class containing extracted stream information."""
    video_url: str
    audio_url: str
    width: int
    height: int
    native_fps: float
    title: str
    duration: Optional[int] = None


@dataclass
class SearchResult:
    """Data class for video search results."""
    id: str
    title: str
    url: str
    thumbnail: str
    duration: str
    view_count: int
    uploader: str


class YouTubeService:
    """
    Service for extracting YouTube video/audio streams and search.
    
    Uses yt-dlp for extraction, prioritizing H.264/MP4 format for
    OpenCV compatibility.
    """
    
    # Common user agent for YouTube requests
    USER_AGENT = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
    
    def __init__(self, remote_components: bool = True):
        """
        Initialize YouTube service.
        
        Args:
            remote_components: Enable remote components for JS challenges
        """
        self._remote_components = remote_components
    
    def get_stream_info(self, youtube_url: str, max_resolution: int = 1080) -> StreamInfo:
        """
        Extract video and audio URLs from a YouTube video.
        
        Prioritizes H.264/AVC codec for OpenCV compatibility.
        
        Args:
            youtube_url: YouTube video URL
            max_resolution: Maximum resolution height (default 1080)
            
        Returns:
            StreamInfo object with extracted URLs and metadata
            
        Raises:
            ValueError: If URL is invalid
            RuntimeError: If extraction fails
        """
        if not youtube_url:
            raise ValueError("YouTube URL cannot be empty")
        
        ydl_opts = {
            # Prioritize H.264 (avc) since AV1/VP9 aren't decodable by OpenCV
            'format': (
                f'bestvideo[height<={max_resolution}][vcodec^=avc]+bestaudio/'
                f'bestvideo[height<={max_resolution}][vcodec^=avc]/'
                f'best[height<={max_resolution}][vcodec^=avc]/'
                f'best[height<={max_resolution}]/'
                f'best'
            ),
            'quiet': True,
            'no_warnings': True,
        }
        
        if self._remote_components:
            ydl_opts['remote_components'] = ['ejs:github']
        
        try:
            logger.info(f"Extracting stream info for: {youtube_url}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                
                video_url, audio_url, width, height, native_fps = self._parse_info(info)
                
                logger.info(f"Extraction complete: {width}x{height} @ {native_fps}fps")
                
                return StreamInfo(
                    video_url=video_url,
                    audio_url=audio_url,
                    width=width,
                    height=height,
                    native_fps=native_fps,
                    title=info.get('title', 'Unknown'),
                    duration=info.get('duration')
                )
                
        except Exception as e:
            logger.error(f"Error extracting stream info: {e}")
            raise RuntimeError(f"Failed to extract video info: {e}")
    
    def _parse_info(self, info: Dict[str, Any]) -> Tuple[str, str, int, int, float]:
        """
        Parse yt-dlp info dict to extract stream URLs and metadata.
        
        Args:
            info: yt-dlp info dictionary
            
        Returns:
            Tuple of (video_url, audio_url, width, height, fps)
        """
        video_url = None
        audio_url = None
        width = 0
        height = 0
        native_fps = 0.0
        
        if 'requested_formats' in info:
            for fmt in info['requested_formats']:
                if fmt.get('vcodec') != 'none':
                    video_url = fmt['url']
                    width = fmt.get('width', 0)
                    height = fmt.get('height', 0)
                    native_fps = float(fmt.get('fps') or 0)
                if fmt.get('acodec') != 'none':
                    audio_url = fmt['url']
        else:
            video_url = info['url']
            audio_url = info['url']
            width = info.get('width', 0)
            height = info.get('height', 0)
            native_fps = float(info.get('fps') or 0)
        
        return video_url, audio_url, width, height, native_fps
    
    def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """
        Search for videos on YouTube.
        
        Args:
            query: Search query string
            max_results: Maximum number of results (default 10)
            
        Returns:
            List of SearchResult objects
        """
        if not query:
            return []
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'max_downloads': max_results,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_url = f'ytsearch{max_results}:{query}'
                info = ydl.extract_info(search_url, download=False)
                
                results = []
                if 'entries' in info:
                    for entry in info['entries']:
                        results.append(SearchResult(
                            id=entry.get('id', ''),
                            title=entry.get('title', 'Sin título'),
                            url=f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                            thumbnail=entry.get('thumbnail', ''),
                            duration=entry.get('duration_string', ''),
                            view_count=entry.get('view_count', 0),
                            uploader=entry.get('uploader', 'Desconocido')
                        ))
                
                return results
                
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise RuntimeError(f"Search failed: {e}")
    
    @staticmethod
    def is_valid_youtube_url(url: str) -> bool:
        """
        Check if a URL is a valid YouTube URL.
        
        Args:
            url: URL string to validate
            
        Returns:
            True if valid YouTube URL, False otherwise
        """
        if not url:
            return False
        
        youtube_domains = ['youtube.com', 'youtu.be', 'www.youtube.com']
        return any(domain in url.lower() for domain in youtube_domains)
