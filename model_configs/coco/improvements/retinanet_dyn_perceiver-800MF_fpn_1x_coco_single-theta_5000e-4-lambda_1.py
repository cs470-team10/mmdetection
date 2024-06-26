_base_ = '../improvements/retinanet_dyn_perceiver-800MF_fpn_1x_coco_single-dyn-base.py'
dynamic_evaluate_epoch = [12] # Training 때 dynamic evaluation을 할 epoch. 안할거면 [], 다할거면 [i + 1 for i in range(12)]
theta_factor = 5000e-4
lambda_factor = 0.5
dynamic_evaluate_on_test = True

model = dict(
    bbox_head=dict(
        loss_dyn=dict(theta_factor=theta_factor, lambda_factor=lambda_factor)
    )
)
val_cfg = dict(dynamic_evaluate_epoch=dynamic_evaluate_epoch)
test_cfg = dict(dynamic_evaluate=dynamic_evaluate_on_test)
