from __future__ import annotations
from stable_diffusion.ldm.util import instantiate_from_config

import math
import random
import sys
from argparse import ArgumentParser

import einops
import k_diffusion as K
import numpy as np
import torch
import torch.nn as nn
from einops import rearrange
from omegaconf import OmegaConf
from PIL import Image, ImageOps
from torch import autocast

sys.path.append("./stable_diffusion")


class CFGDenoiser(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.inner_model = model

    def forward(self, z, sigma, cond, uncond, text_cfg_scale, image_cfg_scale):
        cfg_z = einops.repeat(z, "1 ... -> n ...", n=3)
        cfg_sigma = einops.repeat(sigma, "1 ... -> n ...", n=3)
        cfg_cond = {
            "c_crossattn": [torch.cat([cond["c_crossattn"][0], uncond["c_crossattn"][0], uncond["c_crossattn"][0]])],
            "c_concat": [torch.cat([cond["c_concat"][0], cond["c_concat"][0], uncond["c_concat"][0]])],
        }
        out_cond, out_img_cond, out_uncond = self.inner_model(
            cfg_z, cfg_sigma, cond=cfg_cond).chunk(3)
        return out_uncond + text_cfg_scale * (out_cond - out_img_cond) + image_cfg_scale * (out_img_cond - out_uncond)


def load_model_from_config(config, ckpt, vae_ckpt=None, verbose=False):
    print(f"Loading model from {ckpt}")
    pl_sd = torch.load(ckpt, map_location="cpu")
    if "global_step" in pl_sd:
        print(f"Global Step: {pl_sd['global_step']}")
    sd = pl_sd["state_dict"]
    if vae_ckpt is not None:
        print(f"Loading VAE from {vae_ckpt}")
        vae_sd = torch.load(vae_ckpt, map_location="cpu")["state_dict"]
        sd = {
            k: vae_sd[k[len("first_stage_model."):]] if k.startswith(
                "first_stage_model.") else v
            for k, v in sd.items()
        }
    model = instantiate_from_config(config.model)
    m, u = model.load_state_dict(sd, strict=False)
    if len(m) > 0 and verbose:
        print("missing keys:")
        print(m)
    if len(u) > 0 and verbose:
        print("unexpected keys:")
        print(u)
    return model


def parse_args():
    parser = ArgumentParser()
    parser.add_argument("--resolution", default=512, type=int)
    parser.add_argument("--steps", default=100, type=int)
    parser.add_argument("--config", default="configs/generate.yaml", type=str)
    parser.add_argument(
        "--ckpt", default="checkpoints/instruct-pix2pix-00-22000.ckpt", type=str)
    parser.add_argument("--vae-ckpt", default=None, type=str)
    parser.add_argument("--input", required=False, type=str)
    parser.add_argument("--output", required=False, type=str)
    parser.add_argument("--edit", required=False, type=str)
    parser.add_argument("--cfg-text", default=7.5, type=float)
    parser.add_argument("--cfg-image", default=1.5, type=float)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    return args


def merge_args(args_dict):
    args = parse_args()
    for k, v in args_dict.items():
        setattr(args, k, v)
    return args


class InstructP2P():
    def __init__(self, model_args):
        model_args = merge_args(model_args)
        config = OmegaConf.load(model_args.config)
        self.model = load_model_from_config(
            config, model_args.ckpt, model_args.vae_ckpt)
        self.model.eval().cuda()

    def run(self, args):
        args = merge_args(args)
        model_wrap = K.external.CompVisDenoiser(self.model)
        model_wrap_cfg = CFGDenoiser(model_wrap)
        null_token = self.model.get_learned_conditioning([""])

        seed = random.randint(0, 100000) if args.seed is None else args.seed
        input_image = Image.open(args.input).convert("RGB")
        width, height = input_image.size
        factor = args.resolution / max(width, height)
        factor = math.ceil(min(width, height) * factor / 64) * \
            64 / min(width, height)
        width = int((width * factor) // 64) * 64
        height = int((height * factor) // 64) * 64
        input_image = ImageOps.fit(
            input_image, (width, height), method=Image.Resampling.LANCZOS)

        if args.edit == "":
            input_image.save(args.output)
            return

        with torch.no_grad(), autocast("cuda"), self.model.ema_scope():
            cond = {}
            cond["c_crossattn"] = [
                self.model.get_learned_conditioning([args.edit])]
            input_image = 2 * \
                torch.tensor(np.array(input_image)).float() / 255 - 1
            input_image = rearrange(
                input_image, "h w c -> 1 c h w").to(self.model.device)
            cond["c_concat"] = [
                self.model.encode_first_stage(input_image).mode()]

            uncond = {}
            uncond["c_crossattn"] = [null_token]
            uncond["c_concat"] = [torch.zeros_like(cond["c_concat"][0])]

            sigmas = model_wrap.get_sigmas(args.steps)

            extra_args = {
                "cond": cond,
                "uncond": uncond,
                "text_cfg_scale": args.cfg_text,
                "image_cfg_scale": args.cfg_image,
            }
            torch.manual_seed(seed)
            z = torch.randn_like(cond["c_concat"][0]) * sigmas[0]
            z = K.sampling.sample_euler_ancestral(
                model_wrap_cfg, z, sigmas, extra_args=extra_args)
            x = self.model.decode_first_stage(z)
            x = torch.clamp((x + 1.0) / 2.0, min=0.0, max=1.0)
            x = 255.0 * rearrange(x, "1 c h w -> h w c")
            edited_image = Image.fromarray(x.type(torch.uint8).cpu().numpy())
        edited_image.save(args.output)


# if __name__ == "__main__":
#     args = parse_args()
#     main(args)
