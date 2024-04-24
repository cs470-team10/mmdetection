python3 demo/image_demo.py \
    data/coco/val2017/000000446703.jpg \
    models/retinanet_regnetx-1.6GF_fpn_1x_coco.py \
    --weights models/retinanet_regnetx-1.6GF_fpn_1x_coco_20200517_191403-37009a9d.pth \
    --device cpu

nohup python3 tools/test.py \
    models/retinanet_regnetx-1.6GF_fpn_1x_coco.py \
    models/retinanet_regnetx-1.6GF_fpn_1x_coco_20200517_191403-37009a9d.pth > retina1.6.out &

nohup python3 tools/test.py \
    models/retinanet_regnetx-3.2GF_fpn_1x_coco.py \
    models/retinanet_regnetx-3.2GF_fpn_1x_coco_20200520_163141-cb1509e8.pth > retina3.2.out &

nohup python3 tools/test.py \
    models/retinanet_regnetx-800MF_fpn_1x_coco.py \
    models/retinanet_regnetx-800MF_fpn_1x_coco_20200517_191403-f6f91d10.pth > retina800.out &

nohup python3 tools/test.py \
    models/retinanet_regnetx-800MF_fpn_1x_imageNet_2.py \
    models/retinanet_regnetx-800MF_fpn_1x_coco_20200517_191403-f6f91d10.pth > retina800.out &

nohup python3 tools/test.py \
    models/retinanet_regnetx-800MF_fpn_1x_imageNet.py \
    convert/regnetx_imagenet_pretrained.pth > retina800.out &

nohup python3 tools/test.py \
    models/retinanet_regnetx-800MF_fpn_1x_coco.py \
    models/retinanet_regnetx-800MF_fpn_1x_coco_20200517_191403-f6f91d10.pth > retina800.out &

python3 tools/analysis_tools/get_flops.py models/retinanet_regnetx-1.6GF_fpn_1x_coco.py
python3 tools/analysis_tools/get_flops.py models/retinanet_regnetx-3.2GF_fpn_1x_coco.py

python3 tools/train.py models/retinanet_regnetx-1.6GF_fpn_1x_coco.py
python3 tools/train.py models/retinanet_regnetx-3.2GF_fpn_1x_coco.py

nohup python3 tools/train.py \
    baselines/regnet_800mf_wo_dyn_perceiver/retinanet_regnetx-800MF_fpn_1x_imageNet.py \
    --auto-scale-lr > retina800_finetune.out &
nohup python3 tools/test.py \
    baselines/regnet_800mf_wo_dyn_perceiver/retinanet_regnetx-800MF_fpn_1x_imageNet.py \
    work_dirs/retinanet_regnetx-800MF_fpn_1x_imageNet/epoch_12.pth > retina800.out &

# Convert weight
python3 tools/model_converters/dyn2mmdet.py \
    ./baselines/regnety_800mf_with_dyn_perceiver/reg800m_perceiver_t128.pth \
    ./baselines/regnety_800mf_with_dyn_perceiver/reg800m_perceiver_t128_converted.pth

nohup python3 tools/train.py \
    baselines/regnety_800mf_with_dyn_perceiver/retinanet_dyn_perceiver-800MF_fpn_1x_imageNet6.py \
    --auto-scale-lr --resume > dyn_perceiver_finetune6-1.out &

python3 tools/cs470/analysis_log.py \
    --src ./work_dirs/retinanet_regnetx-800MF_fpn_1x_imageNet/20240410_065852/20240410_065852.log \
    --dest ./


nohup python3 tools/train.py \
    baselines/regnety_800mf_with_dyn_perceiver/retinanet_dyn_perceiver-800MF_fpn_1x_imageNet-t1.py \
    --auto-scale-lr > dyn_perceiver_finetune-t1.out &

nohup python3 tools/train.py \
    baselines/regnety_800mf_with_dyn_perceiver/retinanet_dyn_perceiver-800MF_fpn_1x_imageNet-t2.py \
    --auto-scale-lr > dyn_perceiver_finetune-t2.out &

nohup python3 tools/train.py \
    baselines/regnety_800mf_with_dyn_perceiver/retinanet_dyn_perceiver-800MF_fpn_1x_imageNet-t3.py \
    --auto-scale-lr > dyn_perceiver_finetune-t3.out &

nohup python3 tools/train.py \
    baselines/regnety_800mf_with_dyn_perceiver/retinanet_dyn_perceiver-800MF_fpn_1x_imageNet-t4.py \
    --auto-scale-lr > dyn_perceiver_finetune-t4.out &