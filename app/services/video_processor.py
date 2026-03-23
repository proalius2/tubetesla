"""
Video Processor Module

Handles video frame extraction and processing using OpenCV or FFmpeg.
Supports both direct MP4 URLs and DASH/HLS manifests.
"""

import cv2
import io
import queue
import subprocess
import threading
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ProcessorSettings:
    """Settings for video processing."""
    max_width: int = 1280
    quality: int = 85
    fps_limit: int = 0  # 0 = no limit
    native_fps: float = 25.0
    frame_skip: int = 1
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProcessorSettings':
        """Create settings from dictionary."""
        return cls(
            max_width=data.get('max_width', 1280),
            quality=data.get('quality', 85),
            fps_limit=data.get('fps_limit', 0),
            native_fps=data.get('native_fps', 25.0),
            frame_skip=data.get('frame_skip', 1)
        )


class VideoStreamProcessor:
    """
    Processes video frames from URL streams.
    
    Supports:
    - OpenCV direct decoding (MP4 URLs)
    - FFmpeg decoding (DASH, HLS, manifests)
    - Frame rate limiting
    - Resolution scaling
    - JPEG encoding with quality control
    
    Thread-safe queue-based frame delivery.
    """
    
    # Queue size for frame buffering
    QUEUE_SIZE = 5
    
    def __init__(self):
        """Initialize processor with empty state."""
        self.active = True
        self.frame_queue: queue.Queue = queue.Queue(maxsize=self.QUEUE_SIZE)
        self.error: Optional[str] = None
        self.skip_frames: int = 0
        self.current_pts: float = 0.0
        self._cap: Optional[cv2.VideoCapture] = None
        self._proc: Optional[subprocess.Popen] = None
    
    def stop(self) -> None:
        """
        Stop processing immediately and release resources.
        
        Safe to call multiple times.
        """
        self.active = False
        
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as e:
                logger.warning(f"Error releasing VideoCapture: {e}")
            self._cap = None
        
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception as e:
                logger.warning(f"Error killing ffmpeg process: {e}")
            self._proc = None
        
        logger.info("Video processor stopped")
    
    def process_frames(self, video_url: str, settings: ProcessorSettings) -> None:
        """
        Process video frames in a separate thread.
        
        Attempts OpenCV first, falls back to FFmpeg if needed.
        
        Args:
            video_url: URL of the video stream
            settings: Processing settings
        """
        # Try OpenCV first
        cap = cv2.VideoCapture(video_url)
        
        if cap.isOpened():
            logger.info("Using OpenCV for frame decoding")
            self._process_frames_cv2(cap, settings)
        else:
            cap.release()
            logger.info("OpenCV failed, using FFmpeg fallback")
            self._process_frames_ffmpeg(video_url, settings)
    
    def _process_frames_cv2(self, cap: cv2.VideoCapture, settings: ProcessorSettings) -> None:
        """
        Decode frames using OpenCV (for direct MP4 URLs).
        
        Args:
            cap: Opened VideoCapture object
            settings: Processing settings
        """
        self._cap = cap
        frame_count = 0
        skip = settings.frame_skip
        
        try:
            while self.active:
                ret, frame = cap.read()
                
                if not ret:
                    logger.info("OpenCV: End of stream or read error")
                    break
                
                # Skip frames for audio sync
                to_skip = self.skip_frames
                if to_skip > 0:
                    self.skip_frames = 0
                    logger.debug(f"Skipping {to_skip} frames for sync")
                    for _ in range(to_skip - 1):
                        cap.read()
                    continue
                
                frame_count += 1
                
                if frame_count % skip != 0:
                    continue
                
                # Resize if needed
                if settings.max_width > 0 and frame.shape[1] > settings.max_width:
                    ratio = settings.max_width / frame.shape[1]
                    new_size = (settings.max_width, int(frame.shape[0] * ratio))
                    frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)
                
                # Update PTS (presentation timestamp)
                self.current_pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                
                # Convert to JPEG
                jpeg_data = self._encode_frame_jpeg(frame, settings.quality)
                if jpeg_data:
                    self._enqueue_frame(jpeg_data)
                
                # FPS limiting
                if settings.fps_limit > 0:
                    time.sleep(1.0 / settings.fps_limit)
        
        except Exception as e:
            logger.error(f"OpenCV processing error: {e}")
            self.error = str(e)
            self.active = False
        
        finally:
            cap.release()
            logger.info("OpenCV: VideoCapture released")
    
    def _process_frames_ffmpeg(self, video_url: str, settings: ProcessorSettings) -> None:
        """
        Decode frames using FFmpeg (for DASH, HLS, manifests).
        
        Args:
            video_url: URL of the video stream
            settings: Processing settings
        """
        max_width = settings.max_width
        native_fps = settings.native_fps
        fps_limit = settings.fps_limit
        
        # Determine output FPS
        fps = fps_limit if fps_limit > 0 else (native_fps if native_fps > 0 else 25)
        fps = min(fps, 60)
        
        logger.info(f"FFmpeg: native_fps={native_fps}, fps_limit={fps_limit}, output_fps={fps}")
        
        # Map quality to FFmpeg MJPEG quality (2=best, 31=worst)
        ffmpeg_q = max(2, min(20, int(20 - (settings.quality / 100) * 18)))
        
        # Build FFmpeg command
        cmd = [
            'ffmpeg', '-loglevel', 'error',
            '-user_agent', YouTubeService.USER_AGENT if 'YouTubeService' in dir() else 'Mozilla/5.0',
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5',
            '-allowed_extensions', 'ALL',
            '-i', video_url,
            '-an',  # No audio (handled separately)
            '-vf', f"scale='min({max_width},iw)':-2",
            '-r', str(fps),
            '-q:v', str(ffmpeg_q),
            '-f', 'mjpeg',
            'pipe:1'
        ]
        
        logger.debug(f"FFmpeg command: {' '.join(cmd[:8])}...")
        
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )
        except Exception as e:
            logger.error(f"Failed to start FFmpeg: {e}")
            self.error = f"FFmpeg not available: {e}"
            self.active = False
            return
        
        buf = b''
        frame_index = 0
        
        try:
            while self.active:
                chunk = self._proc.stdout.read(65536)
                
                if not chunk:
                    if self._proc.poll() is not None:
                        stderr = self._proc.stderr.read().decode('utf-8', errors='replace')
                        if stderr:
                            logger.warning(f"FFmpeg stderr: {stderr[:300]}")
                        logger.info("FFmpeg: Process terminated")
                        break
                    continue
                
                buf += chunk
                
                # Extract complete JPEG frames from MJPEG stream
                while True:
                    start = buf.find(b'\xff\xd8')  # JPEG SOI marker
                    if start == -1:
                        buf = b''
                        break
                    
                    end = buf.find(b'\xff\xd9', start + 2)  # JPEG EOI marker
                    if end == -1:
                        buf = buf[start:]
                        break
                    
                    jpeg = buf[start:end + 2]
                    buf = buf[end + 2:]
                    
                    frame_index += 1
                    self.current_pts = frame_index / fps
                    
                    # Skip frames for sync
                    to_skip = self.skip_frames
                    if to_skip > 0:
                        self.skip_frames = max(0, to_skip - 1)
                        continue
                    
                    self._enqueue_frame(jpeg)
        
        except Exception as e:
            logger.error(f"FFmpeg processing error: {e}")
            self.error = str(e)
            self.active = False
        
        finally:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass
            logger.info("FFmpeg: Process stopped")
    
    def _encode_frame_jpeg(self, frame: np.ndarray, quality: int) -> Optional[bytes]:
        """
        Encode a frame as JPEG.
        
        Args:
            frame: BGR frame from OpenCV
            quality: JPEG quality (1-100)
            
        Returns:
            JPEG bytes or None on error
        """
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"JPEG encoding error: {e}")
            return None
    
    def _enqueue_frame(self, jpeg_data: bytes) -> None:
        """
        Add frame to queue, dropping if full.
        
        Args:
            jpeg_data: JPEG encoded frame bytes
        """
        try:
            self.frame_queue.put(jpeg_data, block=False)
        except queue.Full:
            pass  # Drop frame if queue is full
    
    def get_frame(self, timeout: float = 1.0) -> Optional[bytes]:
        """
        Get next frame from queue.
        
        Args:
            timeout: Maximum time to wait for frame
            
        Returns:
            Frame bytes or None if timeout/empty
        """
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None
