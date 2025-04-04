import base64
import requests
from bs4 import BeautifulSoup
import os
import subprocess
import tempfile
import sys
from urllib.parse import urlparse, urljoin
import argparse
import concurrent.futures
from tqdm import tqdm
from PIL import Image, UnidentifiedImageError
import io
import re

# Default configuration
DEFAULT_CONFIG = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'timeout': 30,
    'javascript_delay': 10000,
    'output_dir': 'output_pdfs',
    'max_workers': 4,
    'retry_times': 2,
    'convert_webp_to_jpeg': True,
    'image_quality': 85,
    'max_image_size': 10 * 1024 * 1024,  # 10MB
}

def is_webp_image(content):
    """Improved WebP image detection method"""
    try:
        with Image.open(io.BytesIO(content)) as img:
            return img.format == 'WEBP'
    except UnidentifiedImageError:
        return False
    except Exception:
        return False

def normalize_image_url(url, base_url):
    """Normalize image URL, handling URLs starting with // and relative paths"""
    if url.startswith('//'):
        return f'https:{url}'
    elif url.startswith('data:'):
        return None  # data URI doesn't need processing
    elif not urlparse(url).netloc:
        return urljoin(base_url, url)
    return url

def generate_safe_filename(url, index):
    """
    Generate a safe filename based on URL and index
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace(':', '_').replace('.', '_')
        path = parsed.path.replace('/', '_')[:50]  # Limit length
        if not path:
            path = f"page_{index}"
        return f"{domain}_{path}.pdf"
    except:
        return f"page_{index}.pdf"

def fetch_webpage(url, headers, timeout):
    """
    Fetch webpage content with retry mechanism
    """
    for attempt in range(DEFAULT_CONFIG['retry_times'] + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            if attempt == DEFAULT_CONFIG['retry_times']:
                raise
            print(f"Retrying {url}... (attempt {attempt + 1})")

def convert_webp_to_jpeg_in_html(html_content, base_url, config):
    """
    WebP image conversion function
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    for img in soup.find_all('img'):
        img_src = img.get('src')
        if not img_src:
            continue
            
        # Normalize URL
        normalized_url = normalize_image_url(img_src, base_url)
        if not normalized_url:
            continue  # Skip data URI
            
        try:
            # Handle data URI images
            if img_src.startswith('data:'):
                continue
                
            # Set image request headers
            img_headers = {
                'User-Agent': config.get('user_agent', DEFAULT_CONFIG['user_agent']),
                'Referer': base_url,
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            }
            
            # Download image (with size limit)
            max_size = config.get('max_image_size', DEFAULT_CONFIG['max_image_size'])
            response = requests.get(normalized_url, headers=img_headers, stream=True, 
                                 timeout=config.get('timeout', DEFAULT_CONFIG['timeout']))
            response.raise_for_status()
            
            # Read image data in chunks
            img_data = b''
            for chunk in response.iter_content(8192):
                img_data += chunk
                if len(img_data) > max_size:
                    print(f"Skipping large image: {normalized_url[:50]}...")
                    raise ValueError("Image too large")
            
            # Check if it's a WebP image
            if is_webp_image(img_data):
                with Image.open(io.BytesIO(img_data)) as img_pil:
                    # Convert to JPEG
                    jpeg_buffer = io.BytesIO()
                    img_pil.convert('RGB').save(jpeg_buffer, 
                                              format='JPEG', 
                                              quality=config.get('image_quality', DEFAULT_CONFIG['image_quality']))
                    jpeg_data = jpeg_buffer.getvalue()
                    
                    # Replace with data URI
                    img['src'] = f"data:image/jpeg;base64,{base64.b64encode(jpeg_data).decode('utf-8')}"
                    print(f"Converted WebP image: {normalized_url[:50]}...")
            
        except requests.exceptions.RequestException as e:
            print(f"Download failed for {normalized_url[:50]}...: {str(e)}")
            continue
        except Exception as e:
            print(f"Error processing image {normalized_url[:50]}...: {str(e)}")
            continue
            
    return str(soup)

def convert_webpage_to_pdf(url, output_path, config):
    """Conversion function"""
    temp_html_path = None
    try:
        headers = {
            'User-Agent': config.get('user_agent', DEFAULT_CONFIG['user_agent']),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }

        html_content = fetch_webpage(url, headers, config.get('timeout', DEFAULT_CONFIG['timeout']))
        
        # Convert WebP images to JPEG
        if config.get('convert_webp_to_jpeg', DEFAULT_CONFIG['convert_webp_to_jpeg']):
            html_content = convert_webp_to_jpeg_in_html(html_content, url, config)
        else:
            soup = BeautifulSoup(html_content, 'html.parser')
            html_content = str(soup)

        # Inject MathJax and base tags
        soup = BeautifulSoup(html_content, 'html.parser')
        mathjax_script = soup.new_tag(
            "script",
            attrs={
                "src": "https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.9/MathJax.js?config=TeX-MML-AM_CHTML",
                "async": True,
            },
        )
        soup.head.append(mathjax_script)
        base_tag = soup.new_tag("base", href=url)
        soup.head.insert(0, base_tag)

        # Save temporary file
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode='w', encoding='utf-8') as temp_html_file:
            temp_html_path = temp_html_file.name
            temp_html_file.write(str(soup))

        # Convert using wkhtmltopdf
        subprocess.run(
            [
                "wkhtmltopdf",
                "--javascript-delay", str(config.get('javascript_delay', DEFAULT_CONFIG['javascript_delay'])),
                "--no-stop-slow-scripts",
                "--enable-local-file-access",
                "--quiet",
                temp_html_path,
                output_path
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True, None

    except Exception as e:
        return False, str(e)
    finally:
        if temp_html_path and os.path.exists(temp_html_path):
            os.remove(temp_html_path)

def process_single_url(url, output_dir, config, index):
    """
    Process a single URL
    """
    filename = generate_safe_filename(url, index)
    output_path = os.path.join(output_dir, filename)
    
    print(f"Processing {url}...")
    success, error = convert_webpage_to_pdf(url, output_path, config)
    
    if success:
        print(f"Successfully saved to {output_path}")
        return True, url, None
    else:
        print(f"Failed to process {url}: {error}")
        return False, url, error

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Convert webpages to PDF with math formula support.')
    parser.add_argument('url_file', help='Text file containing URLs (one per line)')
    parser.add_argument('-o', '--output-dir', default=DEFAULT_CONFIG['output_dir'], 
                       help='Output directory for PDF files')
    parser.add_argument('-d', '--delay', type=int, default=DEFAULT_CONFIG['javascript_delay'],
                       help='JavaScript delay in milliseconds')
    parser.add_argument('-j', '--jobs', type=int, default=DEFAULT_CONFIG['max_workers'],
                       help='Number of parallel jobs')
    parser.add_argument('--no-webp-convert', action='store_false', dest='convert_webp',
                       help='Disable WebP to JPEG conversion')
    parser.add_argument('--image-quality', type=int, default=DEFAULT_CONFIG['image_quality'],
                       help='Quality for converted JPEG images (1-100)')
    args = parser.parse_args()

    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)

    # Read URL file
    try:
        with open(args.url_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Error reading URL file: {e}", file=sys.stderr)
        sys.exit(1)

    if not urls:
        print("No URLs found in the input file.", file=sys.stderr)
        sys.exit(1)

    # Prepare complete configuration
    config = {
        'user_agent': DEFAULT_CONFIG['user_agent'],
        'timeout': DEFAULT_CONFIG['timeout'],
        'javascript_delay': args.delay,
        'convert_webp_to_jpeg': args.convert_webp,
        'image_quality': args.image_quality,
    }

    # Process URLs
    success_count = 0
    failure_count = 0
    failures = []

    # Use thread pool for parallel processing
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = []
        for i, url in enumerate(urls):
            futures.append(executor.submit(process_single_url, url, args.output_dir, config, i+1))

        # Show progress bar
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures), desc="Processing URLs"):
            success, url, error = future.result()
            if success:
                success_count += 1
            else:
                failure_count += 1
                failures.append((url, error))

    # Output statistics
    print("\nConversion Summary:")
    print(f"Successfully converted: {success_count}")
    print(f"Failed conversions: {failure_count}")

    if failures:
        print("\nFailed URLs:")
        for url, error in failures:
            print(f"- {url}: {error}")

if __name__ == "__main__":
    main()
