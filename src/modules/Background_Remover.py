from rembg import remove
from PIL import Image, ImageFilter
from pathlib import Path
import io
from glob import glob

global files_processed
files_processed = None

def get_files_processed():
    return files_processed


def remove_background_and_feather(input_path, output_path, feather_radius=4):
    # Read the image
    with open(input_path, "rb") as file:
        input_image = file.read()

    # Remove the background
    output_image = remove(input_image)

    # Convert the result to a PIL image
    img_with_transparency = Image.open(io.BytesIO(output_image))

    # Apply feather (Gaussian Blur) to the alpha channel
    alpha = img_with_transparency.getchannel("A")
    alpha_feathered = alpha.filter(ImageFilter.GaussianBlur(feather_radius))
    img_with_transparency.putalpha(alpha_feathered)

    # Save the final image
    img_with_transparency.save(output_path, "PNG")


def batch_process_images(input_dir, output_dir):
    input_dir_path = Path(input_dir)
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(exist_ok=True)
    global files_processed
    # Process each image in the input directory
    images = list(input_dir_path.glob("*.png")) + list(input_dir_path.glob("*.jpg"))
    if images:
        print("Found the following images: ", [img.stem for img in images])
        files_processed = len(images)
        for image_path in images:
            output_image_path = output_dir_path / image_path.name
            print(f"Processing {image_path}...")
            remove_background_and_feather(image_path, output_image_path)
            print(f"Saved to {output_image_path}")
        return files_processed
    else:
        print("No Images in this Directory")
        return None


# Usage: Specify your input and output directories
if __name__ == "__main__":
    input_path = input("Enter the directory your images are in: ")
    output_path = input("Output Directory: ")

    batch_process_images(input_path, output_path)
