import os
from flask import Flask, request, render_template, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from moviepy.editor import ImageClip, CompositeVideoClip, ColorClip
from PIL import Image
import numpy as np
import time
import glob
from datetime import datetime, timedelta

app = Flask(__name__)

# Configure upload folder based on environment
if os.environ.get('VERCEL_ENV') == 'production':
    app.config['UPLOAD_FOLDER'] = '/tmp'  # Use /tmp for Vercel
elif os.environ.get('DIGITAL_OCEAN_APP') == 'true':
    app.config['UPLOAD_FOLDER'] = '/app/uploads'  # Use persistent storage for DigitalOcean
else:
    app.config['UPLOAD_FOLDER'] = 'uploads'  # Local development

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['VIDEO_LIFETIME'] = 3600  # 1 hour in seconds

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

def create_panning_video(image_path, duration=25, effect='left'):
    # Run cleanup before creating new video
    cleanup_old_files()
    
    # Final video dimensions (9:16 aspect ratio)
    video_width = 1080
    video_height = 1920
    
    # Open and process image
    with Image.open(image_path) as img:
        # Convert to RGB if necessary
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Calculate resize dimensions based on effect direction
        if effect in ['left', 'right']:
            # For horizontal panning, make image 2x wider
            new_width = video_width * 2
            new_height = int((video_height / video_width) * new_width)
            resize_dim = (new_width, new_height)
        else:  # up or down
            # For vertical panning, make image 2x taller
            new_height = video_height * 2
            new_width = int((video_width / video_height) * new_height)
            resize_dim = (new_width, new_height)
        
        # Resize image
        img = img.resize(resize_dim, Image.Resampling.LANCZOS)
        
        # Save temporary file
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_resized.jpg')
        img.save(temp_path)
    
    # Create video clips
    image_clip = ImageClip(temp_path)
    
    # Create a black background
    bg_clip = ColorClip(size=(video_width, video_height), color=(0, 0, 0))
    bg_clip = bg_clip.set_duration(duration)
    
    # Define position function based on effect
    if effect == 'left':
        def pos_func(t):
            # Move from right to left
            progress = t / duration
            x = video_width - (progress * video_width)
            return (x, 'center')
    elif effect == 'right':
        def pos_func(t):
            # Move from left to right
            progress = t / duration
            x = -video_width + (progress * video_width)
            return (x, 'center')
    elif effect == 'up':
        def pos_func(t):
            # Move from bottom to top
            progress = t / duration
            y = video_height - (progress * video_height)
            return ('center', y)
    else:  # down
        def pos_func(t):
            # Move from top to bottom
            progress = t / duration
            y = -video_height + (progress * video_height)
            return ('center', y)
    
    # Set clip properties
    image_clip = (image_clip
                 .set_position(pos_func)
                 .set_duration(duration))
    
    # Combine clips
    final_clip = CompositeVideoClip([bg_clip, image_clip])
    
    # Write output file
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'output.mp4')
    final_clip.write_videofile(output_path, fps=30, codec='libx264', audio=False)
    
    # Clean up
    try:
        os.remove(temp_path)
    except:
        pass
    
    return output_path

@app.route('/')
def index():
    # Clean up old files when homepage is loaded
    cleanup_old_files()
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files[]' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    
    files = request.files.getlist('files[]')
    file = files[0] if files else None
    effect = request.form.get('effect', 'left')  # Get selected effect, default to left
    
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'Please upload a valid image file'}), 400
    
    if effect not in ['left', 'right', 'up', 'down']:
        return jsonify({'error': 'Invalid effect selected'}), 400
    
    try:
        # Get original filename without extension
        original_name = os.path.splitext(secure_filename(file.filename))[0]
        # Create video filename with timestamp and effect
        video_filename = f"{original_name}_{effect}_video_{int(time.time())}.mp4"
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
        file.save(filepath)
        
        # Create video with selected panning effect
        output_path = create_panning_video(filepath, effect=effect)
        
        # Rename the output file to include the original filename and effect
        final_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        os.rename(output_path, final_path)
        
        # Clean up original image file
        try:
            os.remove(filepath)
        except:
            pass
        
        # Calculate expiration time
        expiry_time = datetime.now() + timedelta(seconds=app.config['VIDEO_LIFETIME'])
        
        return jsonify({
            'success': True, 
            'video_path': 'download/' + video_filename,
            'expires_in': app.config['VIDEO_LIFETIME'],
            'expires_at': expiry_time.strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        print(f"Error generating video: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # Check if file exists
    if not os.path.exists(file_path):
        return jsonify({'error': 'File has expired or does not exist'}), 404
    
    # Check if file is too old
    file_age = time.time() - os.path.getctime(file_path)
    if file_age > app.config['VIDEO_LIFETIME']:
        # Clean up expired file
        try:
            os.remove(file_path)
        except:
            pass
        return jsonify({'error': 'File has expired'}), 410
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename
    )

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')

if __name__ == '__main__':
    # Only use debug mode locally
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
