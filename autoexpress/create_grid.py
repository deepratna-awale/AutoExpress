import matplotlib.pyplot as plt
import glob
import matplotlib.image as mpimg
from modules.json_handler import get_expression_list

def plot_images(images, labels, rows, cols, output_file):
    fig, axes = plt.subplots(rows, cols, figsize=(12, 12))
    fig.patch.set_facecolor("#333333")  # Set background color to dark grey
    for ax in axes.flat:
        ax.axis("off")
    for i, ax in enumerate(axes.flat):
        ax.imshow(images[i])
        ax.set_title(labels[i], color="white")  # Set title color to white
    plt.tight_layout()
    plt.savefig(output_file, facecolor=fig.get_facecolor())  # Save figure
    plt.show()


def load_images_from_directory(directory):
    image_list = []
    for filename in glob.glob(directory + "/*.png"):
        image = mpimg.imread(filename)
        image_list.append(image)
    return image_list


def main():
    input_dir = r"D:\Workspace\AI\stable-diffusion-webui\outputs\img2img-images\2024-05-09"
    output_file = r"autoexpress\resources\anime_grid.png"
    rows,cols = 4, 7

    labels = get_expression_list().keys()
    images = load_images_from_directory(input_dir)

    plot_images(images, labels, rows, cols, output_file)


if __name__ == "__main__":
    main()
