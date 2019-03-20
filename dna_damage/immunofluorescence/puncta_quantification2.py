from os import walk
from os.path import join, split
from fnmatch import fnmatch
from numpy import zeros, argmax, arange, stack, sum, mean, std, copy, array
from skimage.io import imread
from skimage.filters import gaussian, sobel, threshold_otsu, threshold_isodata
from skimage.morphology import disk, erosion, reconstruction, remove_small_objects
from skimage.measure import label, regionprops
from pandas import DataFrame

# Define constants.
NO_PIXELS_2_UM2 = 0.10185185185**2

def find_tif_files(folder_name):
    tif_file_path_list = []
    search_str = '*ome.tif'
    for (dir_path, dir_name_list, file_name_list) in walk(folder_name):
        for i_file_name in file_name_list:
            if fnmatch(i_file_name, search_str):
                tif_file_path_list.append(join(dir_path, i_file_name))
    return tif_file_path_list

def extend_depth_field(z_stack_mat):
    no_slices, no_rows, no_columns = z_stack_mat.shape
    sobel_mat = zeros((no_slices, no_rows, no_columns))
    for i in range(no_slices):
        sobel_mat[i, :, :] = sobel(z_stack_mat[i, :, :])
    idx_max_mat = argmax(sobel_mat, axis = 0)
    z_stack_mat = z_stack_mat.reshape((no_slices, -1))
    z_stack_mat = z_stack_mat.transpose()
    extended_mat = z_stack_mat[arange(len(z_stack_mat)), idx_max_mat.ravel()]
    extended_mat = extended_mat.reshape((no_rows, no_columns))
    return extended_mat

def subtract_background(raw_mat, pixel_radius):
    struct_mat = disk(pixel_radius)
    eroded_mat = erosion(raw_mat, struct_mat)
    opened_mat = reconstruction(eroded_mat, raw_mat)
    subtracted_mat = raw_mat - opened_mat
    return subtracted_mat

def express_as_snr(gray_mat, bw_mat):
    offset_mat = gray_mat - mean(gray_mat[~bw_mat])
    snr_mat = offset_mat / std(offset_mat[~bw_mat])
    return snr_mat

def stack_snr_lambda(gaussian_lambda_stack_mat, bw_lambda_stack_mat):
    snr_lambda1_mat = express_as_snr(gaussian_lambda_stack_mat[:, :, 0], bw_lambda_stack_mat[:, :, 0])
    snr_lambda2_mat = express_as_snr(gaussian_lambda_stack_mat[:, :, 1], bw_lambda_stack_mat[:, :, 1])
    snr_lambda3_mat = express_as_snr(gaussian_lambda_stack_mat[:, :, 2], bw_lambda_stack_mat[:, :, 2])
    snr_lambda_stack_mat = stack((snr_lambda1_mat, snr_lambda2_mat, snr_lambda3_mat), axis = -1)
    return snr_lambda_stack_mat

def make_dataframe(lambda1_regionprops_list, lambda2_regionprops_list, lambda3_regionprops_list):
    no_lambda1_regions = len(lambda1_regionprops_list)
    mean_lambda1_au_row = array([x.mean_intensity for x in lambda1_regionprops_list])
    lambda1_area_row = NO_PIXELS_2_UM2 * array([x.area for x in lambda1_regionprops_list])
    no_lambda2_regions_row = array([len(x) for x in lambda2_regionprops_list])
    no_lambda3_regions_row = array([len(x) for x in lambda3_regionprops_list])
    data_dict = {'mean lambda_1 au': mean_lambda1_au_row,
    'lambda_1 area': lambda1_area_row,
    'no lambda_2 regions': no_lambda2_regions_row,
    'no lambda_3 regions': no_lambda3_regions_row}
    data_frame = DataFrame(data = data_dict)
    return data_frame

def get_region_properties(gaussian_lambda_stack_mat, bw_lambda_stack_mat):
    snr_lambda_stack_mat = stack_snr_lambda(gaussian_lambda_stack_mat, bw_lambda_stack_mat)
    label_lambda1_mat, no_lambda1_regions = label(bw_lambda_stack_mat[:, :, 0], return_num = True)
    lambda1_regionprops_list = regionprops(label_lambda1_mat, snr_lambda_stack_mat[:, :, 0])
    lambda2_regionprops_list = []
    lambda3_regionprops_list = []
    for i in range(1, no_lambda1_regions + 1):
        i_bw_lambda1_mat = label_lambda1_mat == i
        i_bw_lambda2_mat = copy(bw_lambda_stack_mat[:, :, 1])
        i_bw_lambda2_mat[~i_bw_lambda1_mat] = False
        i_lambda2_regionprops_list = regionprops(label(i_bw_lambda2_mat), snr_lambda_stack_mat[:, :, 1])
        lambda2_regionprops_list.append(i_lambda2_regionprops_list)
        i_bw_lambda3_mat = copy(bw_lambda_stack_mat[:, :, 2])
        i_bw_lambda3_mat[~i_bw_lambda1_mat] = False
        i_lambda3_regionprops_list = regionprops(label(i_bw_lambda3_mat), snr_lambda_stack_mat[:, :, 2])
        lambda3_regionprops_list.append(i_lambda3_regionprops_list)
    return lambda1_regionprops_list, lambda2_regionprops_list, lambda3_regionprops_list

def segment_stack(stack_file_path):
    mm_stack = imread(stack_file_path)
    no_channels, no_slices, no_rows, no_columns = mm_stack.shape
    # Extend depth of field.
    extended_lambda1_mat = extend_depth_field(mm_stack[0, :, :, :])
    extended_lambda2_mat = extend_depth_field(mm_stack[1, :, :, :])
    extended_lambda3_mat = extend_depth_field(mm_stack[2, :, :, :])
    # Segment nucleus.
    gaussian_lambda1_mat = gaussian(extended_lambda1_mat, sigma = 3)
    bw_lambda1_mat = gaussian_lambda1_mat >= threshold_otsu(gaussian_lambda1_mat)
    # Segment puncta.
    gaussian_lambda2_mat = gaussian(extended_lambda2_mat, sigma = 2)
    gaussian_lambda3_mat = gaussian(extended_lambda3_mat, sigma = 2)
    subtracted_lambda2_mat = subtract_background(gaussian_lambda2_mat, 5)
    subtracted_lambda3_mat = subtract_background(gaussian_lambda3_mat, 5)
    bw_lambda2_mat = subtracted_lambda2_mat >= threshold_isodata(subtracted_lambda2_mat[bw_lambda1_mat])
    bw_lambda3_mat = subtracted_lambda3_mat >= threshold_isodata(subtracted_lambda3_mat[bw_lambda1_mat])
    # Remove small objects.
    bw_lambda2_mat[~bw_lambda1_mat] = False
    bw_lambda3_mat[~bw_lambda1_mat] = False
    bw_lambda2_mat = remove_small_objects(bw_lambda2_mat, sum(disk(2)))
    bw_lambda3_mat = remove_small_objects(bw_lambda3_mat, sum(disk(2)))
    # Stack results.
    gaussian_lambda_stack_mat = stack((gaussian_lambda1_mat, gaussian_lambda2_mat, gaussian_lambda3_mat), axis = -1)
    bw_lambda_stack_mat = stack((bw_lambda1_mat, bw_lambda2_mat, bw_lambda3_mat), axis = -1)
    return gaussian_lambda_stack_mat, bw_lambda_stack_mat
