_base_ ='../improvements/retinanet_dyn_perceiver-800MF_fpn_1x_ilsvrc_single-dyn-theta_115e-4-lambda_1.py'

NUM_IMAGES = [[1360, 742, 37, 112], [1219, 841, 46, 145], [1077, 906, 57, 211], [933, 993, 68, 257], [827, 1022, 73, 329], [725, 1043, 90, 393], [628, 1049, 102, 472], [535, 1038, 122, 556], [458, 1016, 126, 651], [398, 1003, 129, 721], [342, 956, 146, 807], [282, 915, 148, 906], [236, 867, 149, 999], [203, 786, 158, 1104], [176, 697, 170, 1208], [166, 594, 176, 1315], [147, 513, 185, 1406], [147, 513, 185, 1406], [132, 431, 192, 1496], [119, 360, 198, 1574], [108, 307, 197, 1639], [94, 258, 199, 1700], [89, 197, 201, 1764], [84, 145, 205, 1817], [75, 113, 203, 1860], [57, 89, 201, 1904], [50, 80, 193, 1928], [41, 75, 176, 1959], [36, 65, 160, 1990], [27, 58, 127, 2039], [18, 54, 100, 2079], [8, 44, 85, 2114], [7, 35, 61, 2148], [0, 0, 0, 2251]]

test_cfg = dict(num_images=NUM_IMAGES)