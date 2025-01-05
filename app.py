import os
from flask import Flask, request, render_template, jsonify, send_file
from werkzeug.utils import secure_filename
from moviepy.editor import ImageClip, CompositeVideoClip, ColorClip
from PIL import Image
import numpy as np
import time
import glob
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
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

def create_panning_video(image_path, duration=25):
    # Run cleanup before creating new video
    cleanup_old_files()
    
    # Final video dimensions (9:16 aspect ratio)
    video_width = 1080
    video_height = 1920
    
    # Load and process the image
    img = Image.open(image_path)
    
    # Calculate dimensions for the enlarged image
    aspect_ratio = img.width / img.height
    enlarged_width = int(video_width * 2)  # Make image 2x wider than video frame
    enlarged_height = int(enlarged_width / aspect_ratio)
    
    # Ensure the image is tall enough
    if enlarged_height < video_height:
        enlarged_height = video_height
        enlarged_width = int(enlarged_height * aspect_ratio)
    
    # Resize image using Lanczos resampling
    img = img.resize((enlarged_width, enlarged_height), Image.Resampling.LANCZOS)
    
    # Convert to RGB mode if necessary
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    
    # Save the resized image as a temporary file
    temp_img_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_resized.jpg')
    img.save(temp_img_path, quality=95)
    
    # Create a black background clip
    bg_clip = ColorClip(size=(video_width, video_height), 
                       color=(0, 0, 0), 
                       duration=duration)
    
    # Create the image clip
    clip = ImageClip(temp_img_path)
    
    def get_frame_position(t):
        # Calculate position for smooth panning from right to left
        progress = t / duration
        
        # Start position (right side)
        x_start = -(enlarged_width - video_width)
        # End position (left side)
        x_end = 0
        
        # Linear interpolation from start to end position
        x = x_start + (x_end - x_start) * progress
        
        # Center vertically
        y = (video_height - enlarged_height) // 2
        
        return (int(x), int(y))
    
    # Create the moving clip
    moving_clip = (clip
                  .set_duration(duration)
                  .set_position(get_frame_position))
    
    # Combine clips and crop to final size
    final_clip = (CompositeVideoClip([bg_clip, moving_clip])
                 .set_duration(duration))
    
    # Write to output file
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'output.mp4')
    final_clip.write_videofile(output_path, fps=30, codec='libx264')
    
    # Clean up temporary files
    try:
        os.remove(temp_img_path)
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
    
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'Please upload a valid image file'}), 400
    
    try:
        # Get original filename without extension
        original_name = os.path.splitext(secure_filename(file.filename))[0]
        # Create video filename with timestamp
        video_filename = f"{original_name}_video_{int(time.time())}.mp4"
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
        file.save(filepath)
        
        # Create video with panning effect
        output_path = create_panning_video(filepath)
        
        # Rename the output file to include the original filename
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
