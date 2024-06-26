from dyn_perceiver.dyn_perceiver_regnet_model import DynPerceiver
import torch.nn as nn
from mmdet.registry import MODELS
from mmengine.model import BaseModule
from cs470_logger.cs470_debug_print import cs470_debug_print

@MODELS.register_module()
class DynPerceiverBaseline(BaseModule):
    def __init__(self, init_cfg, test_num, num_classes=1000, **args):
        super(DynPerceiverBaseline, self).__init__(init_cfg)
        self.dyn_perceiver = DynPerceiver(
            num_latents=128,
            num_classes=num_classes,
            cnn_arch='regnet_y_800mf',
            depth_factor=[1,1,1,2],
            spatial_reduction=True,
            with_last_CA=True,
            SA_widening_factor=4,
            with_x2z=True,
            with_dwc=True,
            with_z2x=True,
            with_isc=True)
        if (init_cfg == None or init_cfg['type'] != 'Pretrained' or init_cfg['checkpoint'] == None or not isinstance(init_cfg['checkpoint'], str)):
            raise 'A pretrained model must be provided.'
        self.test_num = test_num
        self._freeze_stages()
        self.threshold = None

    def forward(self, x):
        y_early3, y_att, y_cnn, y_merge, outs = self.dyn_perceiver.forward(x)
        # torch.Size([2, 64, 200, 304])
        # torch.Size([2, 144, 100, 152])
        # torch.Size([2, 320, 50, 76])
        # torch.Size([2, 784, 25, 38])
        return outs, y_early3, y_att, y_cnn, y_merge
    
    def set_threshold(self, threshold):
        self.threshold = threshold
    
    def unset_threshold(self):
        self.threshold = None

    def get_last_exited_stage(self):
        return self.dyn_perceiver.get_last_exited_stage()
    
    def train(self, mode=True):
        self.dyn_perceiver.train(mode)
        self._freeze_stages()

    def _freeze_stages(self):
        # freeze stages
        test_num = self.test_num
        for name, param in self.dyn_perceiver.named_parameters():
            # cnn stem and conv block
            if 'cnn_stem' in name:
                # cs470_debug_print(f"{name} freezed!")
                param.requires_grad = False
            if f"cnn_body.block1" in name:
                # cs470_debug_print(f"{name} freezed!")
                param.requires_grad = False
            
            # classification branch(x2z, z2x, self attention, token mixer, expander; ~ stage 1 범위)
            if test_num == 2:
                # stage 1
                i = 1
                if (f"dwc{str(i)}_x2z" in name) or \
                        (f"cross_att{str(i)}_x2z" in name) or \
                        (f"self_att{str(i)}" in name) or \
                        (f"token_mixer.{str(i - 1)}." in name) or \
                        (f"token_expander.{str(i - 1)}." in name) or \
                        (f"cross_att{str(i + 1)}_z2x" in name):
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
            
            # classification branch(x2z, z2x, self attention, token mixer, expander, latent; ~ stage 1 범위)
            if test_num == 3:
                if "latent" in name:
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
                # stage 1
                i = 1
                if (f"dwc{str(i)}_x2z" in name) or \
                        (f"cross_att{str(i)}_x2z" in name) or \
                        (f"self_att{str(i)}" in name) or \
                        (f"token_mixer.{str(i - 1)}." in name) or \
                        (f"token_expander.{str(i - 1)}." in name) or \
                        (f"cross_att{str(i + 1)}_z2x" in name):
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
            
            # classification branch(x2z, z2x, self attention, token mixer, expander, latent; 전체 범위)
            if test_num == 4:
                if "latent" in name:
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
                # stage 1
                i = 1
                if (f"dwc{str(i)}_x2z" in name) or \
                        (f"cross_att{str(i)}_x2z" in name) or \
                        (f"self_att{str(i)}" in name) or \
                        (f"token_mixer.{str(i - 1)}." in name) or \
                        (f"token_expander.{str(i - 1)}." in name) or \
                        (f"cross_att{str(i + 1)}_z2x" in name):
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
                # stage 2
                i = 2
                if (f"dwc{str(i)}_x2z" in name) or \
                        (f"cross_att{str(i)}_x2z" in name) or \
                        (f"self_att{str(i)}" in name) or \
                        (f"token_mixer.{str(i - 1)}." in name) or \
                        (f"token_expander.{str(i - 1)}." in name) or \
                        (f"cross_att{str(i + 1)}_z2x" in name):
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
                # stage 3
                i = 3
                if (f"dwc{str(i)}_x2z" in name) or \
                        (f"cross_att{str(i)}_x2z" in name) or \
                        (f"self_att{str(i)}" in name) or \
                        (f"token_mixer.{str(i - 1)}." in name) or \
                        (f"token_expander.{str(i - 1)}." in name) or \
                        (f"cross_att{str(i + 1)}_z2x" in name):
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
                # stage 4
                i = 4
                if (f"dwc{str(i)}_x2z" in name) or \
                        (f"cross_att{str(i)}_x2z" in name) or \
                        (f"self_att{str(i)}" in name) or \
                        (f"last_cross_att_z2x" in name):
                    # cs470_debug_print(f"{name} freezed!")
                    param.requires_grad = False
            
        self.dyn_perceiver.cnn_stem.eval()
        # cs470_debug_print("cnn_stem evaluation mode!")
        self.dyn_perceiver.cnn_body.block1.eval()
        # cs470_debug_print("cnn_body.block1 evaluation mode!")
        if test_num == 2 or test_num == 3:
            # stage 1
            self.dyn_perceiver.dwc1_x2z.eval()
            # cs470_debug_print("dwc1_x2z evaluation mode!")
            self.dyn_perceiver.cross_att1_x2z.eval()
            # cs470_debug_print("cross_att1_x2z evaluation mode!")
            self.dyn_perceiver.self_att1.eval()
            # cs470_debug_print("self_att1 evaluation mode!")
            self.dyn_perceiver.token_mixer[0].eval()
            # cs470_debug_print("token_mixer.0 evaluation mode!")
            self.dyn_perceiver.token_expander[0].eval()
            # cs470_debug_print("token_expander.0 evaluation mode!")
            self.dyn_perceiver.cross_att2_z2x.eval()
            # cs470_debug_print("cross_att2_z2x evaluation mode!")
        if test_num == 4:
            # stage 1
            self.dyn_perceiver.dwc1_x2z.eval()
            # cs470_debug_print("dwc1_x2z evaluation mode!")
            self.dyn_perceiver.cross_att1_x2z.eval()
            # cs470_debug_print("cross_att1_x2z evaluation mode!")
            self.dyn_perceiver.self_att1.eval()
            # cs470_debug_print("self_att1 evaluation mode!")
            self.dyn_perceiver.token_mixer[0].eval()
            # cs470_debug_print("token_mixer.0 evaluation mode!")
            self.dyn_perceiver.token_expander[0].eval()
            # cs470_debug_print("token_expander.0 evaluation mode!")
            self.dyn_perceiver.cross_att2_z2x.eval()
            # cs470_debug_print("cross_att2_z2x evaluation mode!")

            # stage 2
            self.dyn_perceiver.dwc2_x2z.eval()
            # cs470_debug_print("dwc2_x2z evaluation mode!")
            self.dyn_perceiver.cross_att2_x2z.eval()
            # cs470_debug_print("cross_att2_x2z evaluation mode!")
            self.dyn_perceiver.self_att2.eval()
            # cs470_debug_print("self_att2 evaluation mode!")
            self.dyn_perceiver.token_mixer[1].eval()
            # cs470_debug_print("token_mixer.1 evaluation mode!")
            self.dyn_perceiver.token_expander[1].eval()
            # cs470_debug_print("token_expander.1 evaluation mode!")
            self.dyn_perceiver.cross_att3_z2x.eval()
            # cs470_debug_print("cross_att3_z2x evaluation mode!")

            # stage 3
            self.dyn_perceiver.dwc3_x2z.eval()
            # cs470_debug_print("dwc3_x2z evaluation mode!")
            self.dyn_perceiver.cross_att3_x2z.eval()
            # cs470_debug_print("cross_att3_x2z evaluation mode!")
            self.dyn_perceiver.self_att3.eval()
            # cs470_debug_print("self_att3 evaluation mode!")
            self.dyn_perceiver.token_mixer[2].eval()
            # cs470_debug_print("token_mixer.2 evaluation mode!")
            self.dyn_perceiver.token_expander[2].eval()
            # cs470_debug_print("token_expander.2 evaluation mode!")
            self.dyn_perceiver.cross_att4_z2x.eval()
            # cs470_debug_print("cross_att4_z2x evaluation mode!")

            # stage 4
            self.dyn_perceiver.dwc4_x2z.eval()
            # cs470_debug_print("dwc3_x2z evaluation mode!")
            self.dyn_perceiver.cross_att4_x2z.eval()
            # cs470_debug_print("cross_att4_x2z evaluation mode!")
            self.dyn_perceiver.self_att4.eval()
            # cs470_debug_print("self_att4 evaluation mode!")
            self.dyn_perceiver.last_cross_att_z2x.eval()
            # cs470_debug_print("last_cross_att_z2x evaluation mode!")
