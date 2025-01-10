import os
from flask import Flask, request, render_template, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from moviepy.editor import ImageClip, CompositeVideoClip, ColorClip
from PIL import Image
import numpy as np
import time
import glob
from datetime import datetime, timedelta
from threading import Thread
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configure upload folder based on environment
if os.environ.get('VERCEL_ENV') == 'production':
    app.config['UPLOAD_FOLDER'] = '/tmp'
elif os.environ.get('DIGITAL_OCEAN_APP') == 'true':
    app.config['UPLOAD_FOLDER'] = '/app/uploads'
else:
    app.config['UPLOAD_FOLDER'] = 'uploads'

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['VIDEO_LIFETIME'] = 3600  # 1 hour in seconds
app.config['GENERATION_TIMEOUT'] = 120  # 2 minutes timeout for video generation

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Store video generation status
video_status = {}

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_panning_video(image_path, video_id, effect='left', duration=25):
    try:
        logger.info(f"Starting video generation for {video_id}")
        # Update status to processing
        video_status[video_id] = {'status': 'processing', 'progress': 0}
        
        video_width = 1080
        video_height = 1920
        
        # Open and process image
        with Image.open(image_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Calculate resize dimensions based on effect direction
            if effect in ['left', 'right']:
                new_width = video_width * 2
                new_height = int((video_height / video_width) * new_width)
                resize_dim = (new_width, new_height)
            else:  # up or down
                new_height = video_height * 2
                new_width = int((video_width / video_height) * new_height)
                resize_dim = (new_width, new_height)
            
            img = img.resize(resize_dim, Image.Resampling.LANCZOS)
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f'temp_{video_id}.jpg')
            img.save(temp_path)
            video_status[video_id]['progress'] = 20
        
        # Create video clips
        image_clip = ImageClip(temp_path)
        bg_clip = ColorClip(size=(video_width, video_height), color=(0, 0, 0))
        bg_clip = bg_clip.set_duration(duration)
        video_status[video_id]['progress'] = 40
        
        # Define position function based on effect
        if effect == 'left':
            def pos_func(t):
                progress = t / duration
                x = video_width - (progress * video_width)
                return (x, 'center')
        elif effect == 'right':
            def pos_func(t):
                progress = t / duration
                x = -video_width + (progress * video_width)
                return (x, 'center')
        elif effect == 'up':
            def pos_func(t):
                progress = t / duration
                y = video_height - (progress * video_height)
                return ('center', y)
        else:  # down
            def pos_func(t):
                progress = t / duration
                y = -video_height + (progress * video_height)
                return ('center', y)
        
        image_clip = image_clip.set_position(pos_func).set_duration(duration)
        video_status[video_id]['progress'] = 60
        
        final_clip = CompositeVideoClip([bg_clip, image_clip])
        video_status[video_id]['progress'] = 80
        
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], f'output_{video_id}.mp4')
        final_clip.write_videofile(output_path, fps=30, codec='libx264', audio=False, logger=None)
        video_status[video_id]['progress'] = 100
        
        # Clean up temp file
        try:
            os.remove(temp_path)
        except:
            pass
        
        video_status[video_id] = {'status': 'completed', 'output_path': output_path}
        logger.info(f"Video generation completed for {video_id}")
        return output_path
    
    except Exception as e:
        logger.error(f"Error generating video for {video_id}: {str(e)}")
        video_status[video_id] = {'status': 'error', 'error': str(e)}
        raise

def cleanup_old_files():
    """Clean up video files older than 1 hour"""
    current_time = time.time()
    for file in glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], '*.mp4')):
        # Get file creation time
        file_time = os.path.getctime(file)
        # If file is older than 1 hour, delete it
        if current_time - file_time > app.config['VIDEO_LIFETIME']:
            try:
                os.remove(file)
            except:
                pass

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
        # Generate unique ID for this video
        video_id = f"{int(time.time())}_{os.urandom(4).hex()}"
        
        # Save uploaded file
        original_name = os.path.splitext(secure_filename(file.filename))[0]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f'input_{video_id}.jpg')
        file.save(filepath)
        
        # Start video generation in background
        thread = Thread(target=create_panning_video, 
                       args=(filepath, video_id, effect))
        thread.daemon = True
        thread.start()
        
        # Return immediately with video ID
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
    status = video_status.get(video_id, {})
    if not status:
        return jsonify({'error': 'Video not found'}), 404
    
    if status.get('status') == 'completed':
        # Generate video filename
        video_filename = f"video_{video_id}.mp4"
        final_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        
        # Rename the output file
        try:
            os.rename(status['output_path'], final_path)
        except:
            pass
        
        # Calculate expiration time
        expiry_time = datetime.now() + timedelta(seconds=app.config['VIDEO_LIFETIME'])
        
        return jsonify({
            'status': 'completed',
            'video_path': f'download/{video_filename}',
            'expires_in': app.config['VIDEO_LIFETIME'],
            'expires_at': expiry_time.strftime('%Y-%m-%d %H:%M:%S')
        })
    
    elif status.get('status') == 'error':
        return jsonify({
            'status': 'error',
            'error': status.get('error', 'Unknown error occurred')
        })
    
    else:
        return jsonify({
            'status': 'processing',
            'progress': status.get('progress', 0)
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

if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
