import os
from flask import Flask, request, render_template, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from moviepy.editor import ImageClip, CompositeVideoClip, ColorClip
from PIL import Image
import numpy as np
import time
import glob
import json
from datetime import datetime, timedelta
from threading import Thread
import logging
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure upload folder based on environment
if os.environ.get('VERCEL_ENV') == 'production':
    app.config['UPLOAD_FOLDER'] = '/tmp'
elif os.environ.get('DIGITAL_OCEAN_APP') == 'true':
    # Use system temp directory for DigitalOcean
    app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
else:
    app.config['UPLOAD_FOLDER'] = 'uploads'

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['VIDEO_LIFETIME'] = 3600  # 1 hour in seconds
app.config['GENERATION_TIMEOUT'] = 120  # 2 minutes timeout for video generation

# Ensure upload folder exists and has correct permissions
try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    # Set directory permissions to 755
    os.chmod(app.config['UPLOAD_FOLDER'], 0o755)
except Exception as e:
    logger.error(f"Error setting up upload folder: {str(e)}")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def get_status_path(video_id):
    """Get path for status file"""
    return os.path.join(app.config['UPLOAD_FOLDER'], f'status_{video_id}.json')

def save_status(video_id, status_data):
    """Save status to file"""
    try:
        status_path = get_status_path(video_id)
        with open(status_path, 'w') as f:
            json.dump(status_data, f)
        # Set file permissions to 644
        os.chmod(status_path, 0o644)
    except Exception as e:
        logger.error(f"Error saving status: {str(e)}")
        # Try alternate location if primary fails
        try:
            alt_path = os.path.join(tempfile.gettempdir(), f'status_{video_id}.json')
            with open(alt_path, 'w') as f:
                json.dump(status_data, f)
            os.chmod(alt_path, 0o644)
            return alt_path
        except Exception as e2:
            logger.error(f"Error saving status to alternate location: {str(e2)}")

def get_status(video_id):
    """Get status from file"""
    try:
        # Try primary location
        status_path = get_status_path(video_id)
        if os.path.exists(status_path):
            with open(status_path, 'r') as f:
                return json.load(f)
        
        # Try alternate location
        alt_path = os.path.join(tempfile.gettempdir(), f'status_{video_id}.json')
        if os.path.exists(alt_path):
            with open(alt_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error reading status: {str(e)}")
    return None

def cleanup_status_file(video_id):
    """Clean up status file"""
    try:
        # Try both locations
        paths = [
            get_status_path(video_id),
            os.path.join(tempfile.gettempdir(), f'status_{video_id}.json')
        ]
        for path in paths:
            if os.path.exists(path):
                os.remove(path)
    except Exception as e:
        logger.error(f"Error cleaning status file: {str(e)}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_panning_video(image_path, video_id, effect='left', duration=25):
    try:
        logger.info(f"Starting video generation for {video_id}")
        save_status(video_id, {'status': 'processing', 'progress': 0})
        
        video_width = 1080
        video_height = 1920
        
        # Open and process image
        with Image.open(image_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Calculate aspect ratio
            img_aspect = img.width / img.height
            target_aspect = video_width / video_height
            
            if effect in ['left', 'right']:
                # For left/right pan, maintain height and calculate width
                new_height = video_height
                new_width = int(new_height * img_aspect)
                
                # Ensure minimum width for panning
                if new_width < video_width * 2:
                    new_width = video_width * 2
                
                resize_dim = (new_width, new_height)
            else:  # up or down
                # For up/down pan, maintain width and calculate height
                new_width = video_width
                new_height = int(new_width / img_aspect)
                
                # Ensure minimum height for panning
                if new_height < video_height * 2:
                    new_height = video_height * 2
                
                resize_dim = (new_width, new_height)
            
            img = img.resize(resize_dim, Image.Resampling.LANCZOS)
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f'temp_{video_id}.jpg')
            img.save(temp_path)
            save_status(video_id, {'status': 'processing', 'progress': 20})
        
        # Create video clips
        image_clip = ImageClip(temp_path)
        bg_clip = ColorClip(size=(video_width, video_height), color=(0, 0, 0))
        bg_clip = bg_clip.set_duration(duration)
        save_status(video_id, {'status': 'processing', 'progress': 40})
        
        # Define position function based on effect
        if effect == 'left':
            def pos_func(t):
                progress = t / duration
                x = (new_width - video_width) - (progress * (new_width - video_width))
                return (x, 'center')
        elif effect == 'right':
            def pos_func(t):
                progress = t / duration
                x = -(progress * (new_width - video_width))
                return (x, 'center')
        elif effect == 'up':
            def pos_func(t):
                progress = t / duration
                y = (new_height - video_height) - (progress * (new_height - video_height))
                return ('center', y)
        else:  # down
            def pos_func(t):
                progress = t / duration
                y = -(progress * (new_height - video_height))
                return ('center', y)
        
        image_clip = image_clip.set_position(pos_func).set_duration(duration)
        save_status(video_id, {'status': 'processing', 'progress': 60})
        
        final_clip = CompositeVideoClip([bg_clip, image_clip])
        save_status(video_id, {'status': 'processing', 'progress': 80})
        
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], f'output_{video_id}.mp4')
        final_clip.write_videofile(output_path, fps=30, codec='libx264', audio=False, logger=None)
        save_status(video_id, {'status': 'processing', 'progress': 100})
        
        # Clean up temp file
        try:
            os.remove(temp_path)
        except:
            pass
        
        # Save completed status
        save_status(video_id, {'status': 'completed', 'output_path': output_path})
        logger.info(f"Video generation completed for {video_id}")
        return output_path
    
    except Exception as e:
        logger.error(f"Error generating video for {video_id}: {str(e)}")
        save_status(video_id, {'status': 'error', 'error': str(e)})
        raise

def cleanup_old_files():
    """Clean up video files older than 1 hour"""
    current_time = time.time()
    
    def cleanup_directory(directory):
        try:
            # Clean up video files
            for file in glob.glob(os.path.join(directory, '*.mp4')):
                if current_time - os.path.getctime(file) > app.config['VIDEO_LIFETIME']:
                    try:
                        os.remove(file)
                    except:
                        pass
            
            # Clean up status files
            for file in glob.glob(os.path.join(directory, 'status_*.json')):
                if current_time - os.path.getctime(file) > app.config['VIDEO_LIFETIME']:
                    try:
                        os.remove(file)
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error cleaning up directory {directory}: {str(e)}")
    
    # Clean up both primary and temporary directories
    cleanup_directory(app.config['UPLOAD_FOLDER'])
    cleanup_directory(tempfile.gettempdir())

@app.route('/')
def index():
    cleanup_old_files()
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files[]' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files[]')
    file = files[0] if files else None
    effect = request.form.get('effect', 'left')
    
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'Please upload a valid image file'}), 400
    
    if effect not in ['left', 'right', 'up', 'down']:
        return jsonify({'error': 'Invalid effect selected'}), 400
    
    try:
        video_id = f"{int(time.time())}_{os.urandom(4).hex()}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f'input_{video_id}.jpg')
        file.save(filepath)
        
        # Start video generation in background
        thread = Thread(target=create_panning_video, 
                       args=(filepath, video_id, effect))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'video_id': video_id,
            'message': 'Video generation started'
        })
        
    except Exception as e:
        logger.error(f"Error in upload: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/status/<video_id>')
def check_status(video_id):
    status_data = get_status(video_id)
    if not status_data:
        return jsonify({'error': 'Video not found'}), 404
    
    if status_data.get('status') == 'completed':
        video_filename = f"video_{video_id}.mp4"
        final_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        
        try:
            os.rename(status_data['output_path'], final_path)
        except:
            pass
        
        expiry_time = datetime.now() + timedelta(seconds=app.config['VIDEO_LIFETIME'])
        
        # Clean up status file after completion
        cleanup_status_file(video_id)
        
        return jsonify({
            'status': 'completed',
            'video_path': f'download/{video_filename}',
            'expires_in': app.config['VIDEO_LIFETIME'],
            'expires_at': expiry_time.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    elif status_data.get('status') == 'error':
        error_message = status_data.get('error', 'Unknown error occurred')
        # Clean up status file after error
        cleanup_status_file(video_id)
        return jsonify({
            'status': 'error',
            'error': error_message
        })
    
    else:
        return jsonify({
            'status': 'processing',
            'progress': status_data.get('progress', 0)
        })

@app.route('/download/<filename>')
def download(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File has expired or does not exist'}), 404
    
    file_age = time.time() - os.path.getctime(file_path)
    if file_age > app.config['VIDEO_LIFETIME']:
        try:
            os.remove(file_path)
        except:
            pass
        return jsonify({'error': 'File has expired'}), 410
    
    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        # Test file write
        test_file = os.path.join(app.config['UPLOAD_FOLDER'], 'test.txt')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        return jsonify({'status': 'healthy', 'upload_folder': app.config['UPLOAD_FOLDER']})
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
