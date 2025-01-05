# Video Slideshow Generator

A Flask web application that creates video slideshows with panning effects from uploaded images.

## Features

- Upload images and generate video slideshows
- Smooth right-to-left panning effect
- 9:16 aspect ratio (perfect for mobile/stories)
- Temporary file storage (videos expire after 1 hour)
- Clean and modern UI

## Technical Details

- Built with Flask
- Uses MoviePy for video generation
- Pillow for image processing
- Automatic cleanup of old files
- Responsive design with Tailwind CSS

## Development Setup

1. Clone the repository
```bash
git clone <your-repo-url>
cd slideshow_generator
```

2. Create and activate virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Run the application
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Deployment

This application is configured for easy deployment to DigitalOcean App Platform:

1. Push your code to GitHub
2. Go to DigitalOcean App Platform
3. Create a new app and select your GitHub repository
4. Select Python environment
5. The app will automatically detect the requirements and Procfile

## Environment Variables

No environment variables are required for basic operation.

## File Storage

Videos are stored temporarily and automatically deleted after 1 hour to manage storage efficiently.
