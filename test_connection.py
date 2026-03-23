import yt_dlp
import cv2
import sys

url = "https://www.youtube.com/watch?v=BaW_jenozKc" # YouTube Rewind 2010 (short and popular, likely available)

def test_stream():
    print("Testing yt-dlp extraction...")
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'quiet': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_url = info['url']
            print(f"URL extracted: {video_url[:50]}...")
    except Exception as e:
        print(f"yt-dlp error: {e}")
        return

    print("Testing OpenCV VideoCapture...")
    cap = cv2.VideoCapture(video_url)
    if not cap.isOpened():
        print("OpenCV failed to open the URL.")
    else:
        ret, frame = cap.read()
        if ret:
            print("Successfully read a frame.")
        else:
            print("Failed to read frame.")
        cap.release()

if __name__ == "__main__":
    test_stream()
