import cv2
import numpy as np
from paddleocr import PaddleOCR
import os

# Create a dummy image with text
img = np.zeros((100, 300, 3), dtype=np.uint8)
cv2.putText(img, "Hello World", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
cv2.imwrite("test_ocr.png", img)

print("Initializing PaddleOCR...")
try:
    # Use the initialization from the user's snippet
    ocr = PaddleOCR(
        use_doc_orientation_classify=False, 
        use_doc_unwarping=False, 
        use_textline_orientation=False,
        lang='en' # Adding lang='en' to be safe/default
    )
    
    print("Running predict on file...")
    result_file = ocr.predict("test_ocr.png")
    print(f"Result type (file): {type(result_file)}")
    for res in result_file:
        print(f"Res type: {type(res)}")
        print(f"Dir res: {dir(res)}")
        # Try to find text
        if hasattr(res, 'text'):
            print(f"Text attr: {res.text}")
        if hasattr(res, 'json'):
            print(f"JSON attr: {res.json}")
            
    print("-" * 20)
    
    print("Running predict on numpy array...")
    result_np = ocr.predict(img)
    print(f"Result type (np): {type(result_np)}")
    for res in result_np:
        print(f"Res type: {type(res)}")
        # Assuming same structure

except Exception as e:
    print(f"Error: {e}")
