import gc
import operator
import os

import cv2
import matplotlib.pyplot as plt
import numpy as np

import common
import video_utils
from OptimalParams import OptimalParams
from estimator import TfPoseEstimator
from networks import get_graph_path
import pickle
import pandas as pd
from pandas import DataFrame, Series


def create_affined_image(image, pts_src, pts_dst):
    """
    Create affine transformed image
    :param image:
    :param pts_src:
    :param pts_dst:
    :return: affined image
    """
    rows, cols, ch = image.shape
    M = cv2.getAffineTransform(pts_src, pts_dst)
    return cv2.warpAffine(image, M, (cols, rows))


def compare_images(imageA, imageB, rmseX, rmseY, totalRMSE, referenceValue, title):
    """
    Compare the two images
    :param imageA:
    :param imageB:
    :param rmseX:
    :param rmseY:
    :param totalRMSE:
    :param referenceValue:
    :param title:
    :return:
    """
    # setup the figure
    fig = plt.figure(title)
    plt.suptitle("RMSE X: %.2f, RMSE Y: %.2f, TOTAL RMSE: %.2f \n\n Reference Value: %.2f" % (rmseX, rmseY, totalRMSE,
                                                                                              referenceValue))

    # show first image
    fig.add_subplot(1, 2, 1)
    plt.imshow(imageA)
    plt.axis("off")

    # show the second image
    fig.add_subplot(1, 2, 2)
    plt.imshow(imageB)
    plt.axis("off")

    # show the images
    plt.show()


def draw_human(npimg, humans, imgcopy=False):
    """
    Draw skeleton on image
    :param npimg:
    :param humans:
    :param imgcopy:
    :return:
    """
    if imgcopy:
        npimg = np.copy(npimg)
    image_h, image_w = npimg.shape[:2]
    centers = {}

    pair = (0, None)

    for h in humans:
        temp = 0
        for part in h.body_parts:
            temp += h.body_parts[part].score

        if temp > pair[0]:
            lst = list(pair)
            lst[1] = h
            lst[0] = temp
            pair = tuple(lst)

    human = pair[1]
    # draw point
    for i in range(common.CocoPart.Background.value):
        if i not in human.body_parts.keys():
            continue

        body_part = human.body_parts[i]
        center = (int(body_part.x * image_w + 0.5), int(body_part.y * image_h + 0.5))
        centers[i] = center
        cv2.circle(npimg, center, 3, common.CocoColors[i], thickness=3, lineType=8, shift=0)

    # draw line
    for pair_order, pair in enumerate(common.CocoPairsRender):
        if pair[0] not in human.body_parts.keys() or pair[1] not in human.body_parts.keys():
            continue

        npimg = cv2.line(npimg, centers[pair[0]], centers[pair[1]], common.CocoColors[pair_order], 3)

    return npimg


def skeletonize(estimator, given_image, hip, image_name):
    """
    The purpose of this method is to return a skeleton of partial human image (legs)
    :param estimator:
    :param given_image:
    :param hip:
    :param image_name:
    :return:
    """

    # Make sure results folder exist if not create it
    if not os.path.exists(".\\images\\results"):
        os.makedirs(".\\images\\results")

    # Initialize TF Pose Estimator
    w = 432
    h = 368
    scales = None

    # Load dummy image
    dummy_image = common.read_imgfile('./images/full_body1.png', None, None)

    # Get dummy image skeleton
    dummy_image_parts = estimator.inference(dummy_image, scales=scales)

    # Display the dummy image's skeleton
    # image = TfPoseEstimator.draw_humans(dummy_image, dummy_image_parts, imgcopy=True)
    # cv2.imshow('dummy image result', image)
    # cv2.waitKey()

    # Collect 2 points for affine transformation
    pts1 = np.float32(
        [[int(dummy_image_parts[0].body_parts[8].x * h), int(dummy_image_parts[0].body_parts[8].y * w)],
         [int(dummy_image_parts[0].body_parts[11].x * h), int(dummy_image_parts[0].body_parts[11].y * w)],
         [int(dummy_image_parts[0].body_parts[17].x * h), int(dummy_image_parts[0].body_parts[17].y * w)]])
    pts2 = np.float32([hip[0],
                       hip[1],
                       hip[2]])

    # Create affine transformed of the dummy image
    affined_dummy_image = create_affined_image(dummy_image, pts1, pts2)
    affined_dummy_image = cv2.flip(affined_dummy_image, 0)
    # cv2.imshow("affined", affined_dummy_image)
    # cv2.waitKey()

    # Get dummy image skeleton
    dummy_image_parts = estimator.inference(affined_dummy_image, scales=scales)
    # image = TfPoseEstimator.draw_humans(affined_dummy_image, dummy_image_parts, imgcopy=True)
    # cv2.imshow('dummy person result', image)
    # cv2.waitKey()

    # Hip coordinates
    firstPersonHipX = dummy_image_parts[0].body_parts[11].x

    # Combine the two images
    hipX = int(firstPersonHipX * h)
    # Create merged image
    merged_image = np.zeros((h * 2, w, 3), np.uint8)
    merged_image[0:hipX, :] = affined_dummy_image[0:hipX, :]
    merged_image[hipX:hipX + h, :] = given_image[:, :]
    # cv2.imshow('Merged Image', merged_image)
    # cv2.waitKey()

    # Find the merge image's skeleton
    merged_image_parts = estimator.inference(merged_image, scales=scales)
    merged_image_skeleton = draw_human(merged_image, merged_image_parts, imgcopy=False)
    # cv2.imshow('merged person result', merged_image_skeleton)
    # cv2.waitKey()

    # Take only legs and show them
    legs_image = np.zeros((h, w, 3), np.uint8)
    legs_image[:] = 255
    legs_image[:, :] = merged_image_skeleton[hipX: hipX + h, :]
    # cv2.imshow('Legs', legs_image)
    # cv2.waitKey()
    cv2.destroyAllWindows()
    # Write image to results folder
    cv2.imwrite(".\\images\\results\\{}.png".format(image_name), legs_image)
    print("Wrote image #{} to results folder".format(image_name))

    del legs_image, merged_image, merged_image_parts, firstPersonHipX, affined_dummy_image, dummy_image_parts, dummy_image
    gc.collect()


def translation(estimator, upper, upper_name, bottom, bottom_name, scale_factor):
    global count
    height_u, width_u, channels = upper.shape
    height_b, width_b, channels = bottom.shape
    scales = None
    for translate_factor in [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]:
        # merge between upper and bottom
        # create original merged image for future use
        min_orig = min(width_u, width_b)
        orig_image = 255 * np.ones((height_u + height_b, min_orig, 3), np.uint8)
        orig_image[0:height_u, :] = upper[:, 0:min_orig]
        orig_image[height_u:height_u + height_b, :] = bottom[:, 0:min_orig]

        pts1 = np.float32([[0, width_u],
                           [height_u, 0],
                           [height_u, width_u]])

        pts2 = np.float32([[translate_factor, width_b],
                           [translate_factor + height_b, 0],
                           [translate_factor + height_b, width_b]])

        translated_affined_image = create_affined_image(upper, pts1, pts2)
        # if display_images:
        #     path = './images/hagit/'
        #     if not os.path.exists(path):
        #         os.makedirs(path)
        #     cv2.imwrite(r'{0}/translated_affined{1}.png'.format(path,count), translated_affined_image)
        # cv2.imshow('affined result', translated_affined_image)
        # cv2.waitKey()

        # Merge the two images until the hip coordinate
        height_u, width_u, channels = translated_affined_image.shape
        minWidth = min(width_u, width_b)
        merged_image = 255 * np.ones((height_u + height_b, minWidth, 3), np.uint8)
        merged_image[0:height_u, :] = translated_affined_image[:, 0:minWidth]
        merged_image[height_u:height_u + height_b, :] = bottom[:, 0:minWidth]
        if display_images:
            path = './images/hagit/'
            if not os.path.exists(path):
                os.makedirs(path)
            cv2.imwrite(r'{0}/merged_image{1}.png'.format(path, count), merged_image)
            # cv2.imshow('Merged Image', merged_image)
            # cv2.waitKey()

        # calculate the merged image skeleton
        no_skeleton = False
        merged_image_parts = estimator.inference(merged_image, scales=scales)
        for pair_order, pair in enumerate(common.CocoPairsRender):
            if merged_image_parts.__contains__(0) and (
                    pair[0] not in merged_image_parts[0].body_parts.keys() or pair[1] not in merged_image_parts[ 0].body_parts.keys()):
                no_skeleton = True
                break
        if not no_skeleton:
            # draw skeleton on image
            merged_image_skeleton = TfPoseEstimator.draw_humans(merged_image, merged_image_parts, imgcopy=True)
            # present the skeleton
            if display_images:
                path = './images/hagit/'
                if not os.path.exists(path):
                    os.makedirs(path)
                cv2.imwrite(r'{0}/merged_person_result{1}.png'.format(path, count), merged_image_skeleton)
                # cv2.imshow('merged person result', merged_image_skeleton)
                # cv2.waitKey()

            # create original skeleton for comparision
            orig_image_parts = estimator.inference(orig_image, scales=scales)
            # gather all info for comparision
            params = OptimalParams(merged_image_parts, orig_image_parts, translate_factor, scale_factor)
            params.skeleton_image = merged_image_skeleton
            params.has_skeleton = not no_skeleton
            params.calculate_rmse()
            params.calculate_skeleton_score(merged_image_parts)
            params.upper = [upper_name, upper]
            params.bottom = [bottom_name, bottom]
            optimalParamsList.append(params)
        cv2.destroyAllWindows()
        count = count + 1


def find_optimal_scaled_translated():
    global count
    # get pre-process bounding boxes of bottom parts
    with open('human_points.pickle', 'rb') as handle:
        bboxes_bottom = pickle.load(handle)
    # read upper and bottom images
    uppper_images = video_utils.load_images_from_folder("./images/upper/", True)
    bottom_images = video_utils.load_images_from_folder("./images/bottom/", True)
    w = 432
    h = 368
    # create OpenPose estimator
    estimator = TfPoseEstimator(get_graph_path('mobilenet_thin'), target_size=(w, h))
    for upper in uppper_images:
        for bottom in bottom_images:
            for factor in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
                # merge between upper and bottom
                # create affined image
                height_u, width_u, channels = upper[0].shape

                pts1 = np.float32([[0, width_u],
                                   [height_u, 0],
                                   [height_u, width_u]])

                height_b, width_b, channels = bottom[0].shape
                # if display_images:
                # path = './images/hagit/'
                # if not os.path.exists(path):
                #     os.makedirs(path)
                # cv2.imwrite(r'{0}/bottom_result{1}.png'.format(path,count),bottom[0])
                # cv2.imshow('bottom result', bottom[0])
                # cv2.waitKey()
                # Scale down and pad
                scaled_bottom = cv2.resize(bottom[0], (int(width_b * factor), int(height_b * factor)), fx=factor,
                                           fy=factor, interpolation=cv2.INTER_AREA)
                height_b, width_b, channels = scaled_bottom.shape

                # pts2 = []
                # for item in bboxes_bottom:
                #     if item[0] == bottom[1] and item[1] == factor:
                #         pts2 = item[2]
                # if pts2.size == 0:
                pts2 = np.float32([[0, width_b],
                                   [height_b, 0],
                                   [height_b, width_b]])

                # if display_images:
                #     path = './images/hagit/'
                #     if not os.path.exists(path):
                #         os.makedirs(path)
                #     cv2.imwrite(r'{0}/scaled_bottom_result{1}.png'.format(path,count), scaled_bottom)
                # cv2.imshow('scaled bottom result', scaled_bottom)
                # cv2.waitKey()

                upper_affined_image = create_affined_image(upper[0], pts1, pts2)
                # if display_images:
                #     path = './images/hagit/'
                #     if not os.path.exists(path):
                #         os.makedirs(path)
                #     cv2.imwrite(r'{0}/upper_affined_result_#1_{1}.png'.format(path, count), upper_affined_image)
                # cv2.imshow('affined result #1', upper_affined_image)
                # cv2.waitKey()

                # remove black pixel from affined image
                # 1 Convert image into grayscale, and make in binary image for threshold value of 1.
                gray = cv2.cvtColor(upper_affined_image, cv2.COLOR_BGR2GRAY)
                ret, thresh = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)
                # 2  Find contours in image. There will be only one object, so find bounding rectangle for it
                image, contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cnt = contours[0]
                # 3 Crop image and save it to another one
                x, y, w, h = cv2.boundingRect(cnt)
                upper_affined_image = upper_affined_image[y:y + h, x:x + w].copy()
                # if display_images:
                #     path = './images/hagit/'
                #     if not os.path.exists(path):
                #         os.makedirs(path)
                #     cv2.imwrite(r'{0}/upper_affined_result_#2_{1}.png'.format(path,count), upper_affined_image)
                # cv2.imshow('affined result #2', upper_affined_image)
                # cv2.waitKey()

                translation(estimator, upper_affined_image, upper[1], scaled_bottom, bottom[1], factor)


def normalize(values):
    """
    Scale to a 0 mean and unit variance
    :param values:
    :return:
    """
    x = np.asarray(values)
    res = (x - x.mean()) / x.std()
    return res


count = 1
if __name__ == '__main__':
    # this main find the optimal scale and translate params based on calculated confidence
    display_images = False
    optimalParamsList = []
    lam = 0.3
    find_optimal_scaled_translated()
    upper_names = []
    bottom_names = []
    scores = []
    rmses = []
    confidences = []
    scales = []
    translations = []
    for params in optimalParamsList:
        bottom_names.append(params.bottom[0])
        upper_names.append(params.upper[0])
        rmses.append(params.rmse)
        scores.append(params.score)
        scales.append(params.scale)
        translations.append(params.translate)

    print("Mean of RMSEs:{}".format(sum(rmses) / float(len(rmses))))
    rmses_normalized = normalize(rmses)
    scores_normalized = normalize(scores)
    confidences.append((1 - lam) * rmses_normalized + lam * scores_normalized)

    writer = pd.ExcelWriter('results.xlsx')
    df = DataFrame(
        {'Bottom Sample ID': Series(bottom_names), 'Upper Sample ID': Series(upper_names), 'Scale': Series(scales),
         'Translations': Series(translations), 'RMSE': Series(rmses), 'Sum Of OpenPose Skeleton Joints': Series(scores),
         'Dvir\'s Confidence Score': Series(confidences[0])})
    df.to_excel(writer, sheet_name='partial-open-pose', index=False)
    df = DataFrame({'Bottom': Series(list(set(bottom_names))), 'Upper': Series(list(set(upper_names)))})
    df.to_excel(writer, sheet_name='Images', index=False)
    writer.save()

    max_index, max_value = max(enumerate(confidences[0]), key=operator.itemgetter(1))
    max_item = optimalParamsList[max_index]
    print("Scale: {0} Translate: {1} ".format(max_item.scale, max_item.translate))
    cv2.imshow("Best Confidence Skeleton", max_item.skeleton_image)
    cv2.waitKey()
