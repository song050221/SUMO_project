"""시연용 sumo-gui 그림 자료(차량·보행자·나무 이미지)를 PIL로 직접 그려 network/assets/에 만든다.

SUMO 기본 표현(삼각형/단순 도형, 초록 동그라미 보행자)은 발표 화면에서 장난감처럼 보인다.
인터넷에서 이미지를 받지 않고, 위에서 내려다본 모습을 코드로 그려서 쓴다 - 다시 만들 때도
이 스크립트만 돌리면 되고 저작권 문제도 없다.

이미지는 **위쪽이 차 앞**이다(sumo-gui는 raster 이미지를 진행 방향으로 돌려 그린다).
차량 크기(길이·폭)는 이미지가 아니라 vType의 length/width가 정하므로, 이미지 비율만
실제 차(약 4.6m x 1.85m)에 맞춘다.

    python scripts/build_visual_assets.py
"""

import os
import random

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "network", "assets")
VEHICLE_STYLE = os.path.join(ROOT, "network", "vehicle_style.xml")
SUV_SHARE = 0.35   # 색마다 세단/SUV 비율
# sumo-gui는 raster 이미지에 차 색을 곱해서 그린다 - 차종 색을 흰색으로 둬야 이미지 색이 그대로
# 나오고, 대시보드가 경로 재배치 차량에 setColor(마젠타)를 하면 그 색이 곱해져 강조된다
# (검은 차는 곱해도 검어서 강조 고리(highlight)로만 보임).
IMAGE_TINT = "255,255,255"
TAXI_SHARE = 3     # 택시 가중치(전체 가중치 합 약 100 기준)
SS = 4  # 크게 그린 뒤 줄여서 계단 현상을 없앤다(supersampling)

# 한국 도로의 실제 차량 색 비율(흰색·회색·검정이 대부분)을 흉내 낸 팔레트와 가중치
CAR_COLORS = {
    "white":  ((240, 240, 238), 30),
    "pearl":  ((226, 224, 214), 8),
    "silver": ((176, 180, 186), 14),
    "gray":   ((104, 108, 114), 14),
    "black":  ((34, 35, 38), 16),
    "navy":   ((32, 50, 92), 5),
    "blue":   ((44, 96, 170), 4),
    "red":    ((170, 32, 36), 4),
    "beige":  ((196, 170, 128), 2),
    "green":  ((40, 92, 70), 1),
}


def _shade(rgb, k):
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


def draw_car(body, kind="sedan", w=180, h=460):
    """위에서 본 승용차. kind: sedan | suv | taxi."""
    W, H = w * SS, h * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(W * 0.28)
    # 그림자
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([W * .06, H * .03, W * .98, H * .99], r, fill=(0, 0, 0, 90))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(W * .03)))
    d = ImageDraw.Draw(img)
    # 차체 (앞이 위)
    d.rounded_rectangle([W * .04, H * .01, W * .96, H * .98], r, fill=_shade(body, 1.0) + (255,),
                        outline=_shade(body, .55) + (255,), width=int(SS * 3))
    # 보닛·트렁크 하이라이트
    d.rounded_rectangle([W * .14, H * .04, W * .86, H * .20], int(r * .6), fill=_shade(body, 1.12) + (255,))
    d.rounded_rectangle([W * .16, H * .86, W * .84, H * .95], int(r * .5), fill=_shade(body, 1.08) + (255,))
    glass = (38, 52, 66, 255)
    glass_hi = (96, 128, 150, 255)
    roof_top, roof_bot = (H * .36, H * .74) if kind != "suv" else (H * .33, H * .86)
    # 앞유리
    d.polygon([(W * .15, H * .22), (W * .85, H * .22), (W * .80, roof_top), (W * .20, roof_top)], fill=glass)
    d.polygon([(W * .22, H * .235), (W * .45, H * .235), (W * .40, H * .30), (W * .24, H * .30)], fill=glass_hi)
    # 지붕
    d.rounded_rectangle([W * .19, roof_top, W * .81, roof_bot], int(W * .08), fill=_shade(body, .93) + (255,))
    # 뒷유리
    if kind != "suv":
        d.polygon([(W * .20, roof_bot), (W * .80, roof_bot), (W * .84, H * .84), (W * .16, H * .84)], fill=glass)
    else:
        d.rectangle([W * .20, roof_bot, W * .80, H * .90], fill=glass)
    # 옆유리
    d.rectangle([W * .10, roof_top + H * .01, W * .17, roof_bot - H * .01], fill=glass)
    d.rectangle([W * .83, roof_top + H * .01, W * .90, roof_bot - H * .01], fill=glass)
    # 사이드미러
    d.ellipse([W * -.02, H * .25, W * .10, H * .30], fill=_shade(body, .8) + (255,))
    d.ellipse([W * .90, H * .25, W * 1.02, H * .30], fill=_shade(body, .8) + (255,))
    # 전조등 / 후미등
    d.rounded_rectangle([W * .08, H * .015, W * .30, H * .045], SS * 4, fill=(255, 250, 220, 255))
    d.rounded_rectangle([W * .70, H * .015, W * .92, H * .045], SS * 4, fill=(255, 250, 220, 255))
    d.rounded_rectangle([W * .07, H * .945, W * .30, H * .975], SS * 4, fill=(200, 20, 24, 255))
    d.rounded_rectangle([W * .70, H * .945, W * .93, H * .975], SS * 4, fill=(200, 20, 24, 255))
    if kind == "taxi":  # 지붕 택시 표시등
        d.rounded_rectangle([W * .30, H * .50, W * .70, H * .58], SS * 6, fill=(255, 196, 0, 255),
                            outline=(120, 90, 0, 255), width=SS * 2)
    return img.resize((w, h), Image.LANCZOS)


def draw_person(shirt, w=96, h=96):
    """위에서 본 사람(어깨 + 머리). 진행 방향이 위."""
    W, H = w * SS, h * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([W * .14, H * .30, W * .92, H * .80], fill=(0, 0, 0, 80))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(W * .04)))
    d = ImageDraw.Draw(img)
    d.ellipse([W * .08, H * .26, W * .92, H * .74], fill=shirt + (255,), outline=_shade(shirt, .6) + (255,), width=SS * 3)
    d.ellipse([W * .30, H * .28, W * .70, H * .68], fill=(58, 42, 34, 255))       # 머리카락
    d.ellipse([W * .38, H * .22, W * .62, H * .36], fill=(236, 200, 170, 255))    # 이마(앞쪽)
    return img.resize((w, h), Image.LANCZOS)


def draw_led_pedestrian(w=160, h=160):
    """실물 보드의 LED 보행자 - 사람 모양에 LED처럼 파랗게 번지는 빛. 진행 방향이 위."""
    W, H = w * SS, h * SS
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * .06, H * .06, W * .94, H * .94], fill=(40, 120, 255, 95))
    img = glow.filter(ImageFilter.GaussianBlur(W * .08))
    d = ImageDraw.Draw(img)
    d.ellipse([W * .22, H * .22, W * .78, H * .78], outline=(150, 200, 255, 255), width=SS * 4)
    person = draw_person((40, 120, 255), w=int(w * .62), h=int(h * .62)).resize((int(W * .62), int(H * .62)), Image.LANCZOS)
    img.alpha_composite(person, (int(W * .19), int(H * .19)))
    return img.resize((w, h), Image.LANCZOS)


def draw_tree(seed, w=128, h=128):
    """위에서 본 가로수/공원 나무 - 여러 겹의 둥근 잎 뭉치."""
    rng = random.Random(seed)
    W, H = w * SS, h * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([W * .14, H * .16, W * .96, H * .98], fill=(0, 0, 0, 70))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(W * .05)))
    d = ImageDraw.Draw(img)
    base = rng.choice([(58, 118, 52), (70, 132, 58), (48, 104, 50), (84, 140, 64)])
    for i in range(14):
        cx, cy = W * (.5 + rng.uniform(-.2, .2)), H * (.5 + rng.uniform(-.2, .2))
        rr = W * rng.uniform(.17, .27)
        k = rng.uniform(.82, 1.12)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=_shade(base, k) + (255,))
    for i in range(6):  # 햇빛 받는 쪽 하이라이트
        cx, cy = W * (.42 + rng.uniform(-.12, .08)), H * (.40 + rng.uniform(-.12, .08))
        rr = W * rng.uniform(.06, .11)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=_shade(base, 1.3) + (200,))
    return img.filter(ImageFilter.GaussianBlur(SS * .6)).resize((w, h), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    made = []
    for name, (rgb, _) in CAR_COLORS.items():
        for kind in ("sedan", "suv"):
            path = os.path.join(OUT_DIR, f"car_{kind}_{name}.png")
            draw_car(rgb, kind).save(path)
            made.append(path)
    draw_car((250, 190, 20), "taxi").save(os.path.join(OUT_DIR, "car_taxi.png"))
    # 실물 연동(hwtwin) 차량 - 선행 주황 / 후행 하늘색 / 우회 마젠타 (hardware_twin.json colors와 같은 색)
    draw_car((255, 140, 0), "sedan").save(os.path.join(OUT_DIR, "car_hw_lead.png"))
    draw_car((0, 190, 255), "sedan").save(os.path.join(OUT_DIR, "car_hw_follow.png"))
    draw_car((255, 60, 220), "sedan").save(os.path.join(OUT_DIR, "car_hw_diverted.png"))
    draw_person((30, 180, 60)).save(os.path.join(OUT_DIR, "person.png"))   # 대시보드 범례의 보행자 초록
    draw_led_pedestrian().save(os.path.join(OUT_DIR, "pedestrian_led.png"))  # 실물 연동 LED 보행자
    for i in range(4):
        draw_tree(i).save(os.path.join(OUT_DIR, f"tree_{i}.png"))
    write_vehicle_style()
    print(f"{len(os.listdir(OUT_DIR))}개 이미지 -> {OUT_DIR}, 차종 정의 -> {VEHICLE_STYLE}")


def write_vehicle_style():
    """routes.xml 차량은 type을 안 적어서 전부 DEFAULT_VEHTYPE이다. 같은 id의 vTypeDistribution을
    선언하면 차마다 이 중 하나가 뽑혀 색·모양이 다양해진다. **물리 값(길이·가속 등)은 하나도
    안 적는다** - SUMO 기본값 그대로라 주행 동작은 바뀌지 않고 그림만 바뀐다.
    실물 연동 차량(hardware_twin.py)용 차종 hwtwin_lead/follow/diverted도 여기 둔다
    (TraCI로는 imgFile을 못 바꾸므로 미리 정의)."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             "<!-- scripts/build_visual_assets.py가 만든 시연용 차량 그림 정의. 물리 값은 SUMO 기본값 그대로. -->",
             "<additional>",
             '    <vTypeDistribution id="DEFAULT_VEHTYPE">']
    for name, (rgb, weight) in CAR_COLORS.items():
        for kind, share in (("sedan", 1 - SUV_SHARE), ("suv", SUV_SHARE)):
            shape = "passenger/sedan" if kind == "sedan" else "passenger/van"
            lines.append(f'        <vType id="car_{kind}_{name}" vClass="passenger" guiShape="{shape}" '
                         f'color="{IMAGE_TINT}" imgFile="assets/car_{kind}_{name}.png" '
                         f'probability="{weight * share:.2f}"/>')
    lines.append(f'        <vType id="car_taxi" vClass="passenger" guiShape="passenger/sedan" color="{IMAGE_TINT}" '
                 f'imgFile="assets/car_taxi.png" probability="{TAXI_SHARE:.2f}"/>')
    lines.append("    </vTypeDistribution>")
    # 색은 이미지(car_hw_*.png)에 들어 있다. vClass custom1 - 신양초 사거리 차도는 이 차종만 다닐 수 있다
    # (network/sinyang_closed.edg.xml, 2026-09-30)
    for role in ("lead", "follow", "diverted"):
        lines.append(f'    <vType id="hwtwin_{role}" vClass="custom1" guiShape="passenger/sedan" length="4.60" '
                     f'width="1.90" color="{IMAGE_TINT}" imgFile="assets/car_hw_{role}.png"/>')
    lines.append(f'    <vType id="DEFAULT_PEDTYPE" vClass="pedestrian" color="{IMAGE_TINT}" guiShape="pedestrian" '
                 'imgFile="assets/person.png"/>')
    lines.append("</additional>")
    with open(VEHICLE_STYLE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
