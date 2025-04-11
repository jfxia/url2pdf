# url2pdf

### Extract the content contained in multiple web page links and convert to PDF files, especially those containing math formulas and webp images.

-The web page URLs are saved in **links.txt**.

-Before running, please install **wkhtmltopdf** (https://wkhtmltopdf.org/downloads.html) and other dependencies.

```
pip install base64 requests bs4 urllib tqdm PIL
```

Usage:

```
python url2pdf.py  links.txt
```

**Note: Some websites have blocked crawler programs, and this script may not work.**
