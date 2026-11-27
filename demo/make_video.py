import math, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1280, 720, 30
GROUND=(8,14,13); PANE=(12,21,19); SURF=(19,29,27); LINE=(29,42,39); TEXT=(232,240,238); MUTED=(139,160,155); FAINT=(86,108,103)
TEAL=(92,211,195); CORAL=(229,139,123); MINT=(160,235,220)
REPO = sys.argv[1]
SERIF = os.path.join(REPO, "assets/fonts/InstrumentSerif-Regular.ttf")
SERIF_I = os.path.join(REPO, "assets/fonts/InstrumentSerif-Italic.ttf")
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"
SANSB = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
def F(p, s): return ImageFont.truetype(p, s)
def ease(t): t = max(0, min(1, t)); return t*t*(3-2*t)
def mix(a, b, t): return tuple(int(a[i]+(b[i]-a[i])*t) for i in range(3))
def fade(img, a):  # a 0..1 toward ground
    return Image.blend(Image.new("RGB",(W,H),GROUND), img, max(0,min(1,a)))

def base():
    im = Image.new("RGB", (W,H), GROUND)
    return im, ImageDraw.Draw(im)

def center(d, text, y, font, fill, cx=W//2):
    w = d.textlength(text, font=font); d.text((cx-w/2, y), text, font=font, fill=fill)

def typed(text, t, start, cps=22):
    n = int(max(0, t-start)*cps); return text[:n]

def orb(im, cx, cy, r, t, level=0.3, color=TEAL):
    layer = Image.new("RGB", (W,H), GROUND); d = ImageDraw.Draw(layer)
    for i in range(6, 0, -1):
        rr = r*(1+0.18*i*(0.6+level*math.sin(t*3+i)))
        d.ellipse((cx-rr, cy-rr, cx+rr, cy+rr), fill=mix(GROUND, color, 0.06+0.03*(7-i)*level))
    d.ellipse((cx-r, cy-r, cx+r, cy+r), fill=mix(GROUND, color, 0.9))
    d.ellipse((cx-r*0.55, cy-r*0.7, cx+r*0.2, cy-r*0.1), fill=mix(color, MINT, 0.5))
    layer = layer.filter(ImageFilter.GaussianBlur(1.2))
    im.paste(layer)

def window(d, x, y, w, h, title="Zoha"):
    d.rounded_rectangle((x,y,x+w,y+h), 18, fill=PANE, outline=LINE, width=2)
    d.line((x, y+46, x+w, y+46), fill=LINE, width=2)
    for i,c in enumerate((CORAL, (230,200,110), TEAL)): d.ellipse((x+20+i*22, y+17, x+32+i*22, y+29), fill=c)
    d.text((x+w/2-d.textlength(title, font=F(SANS,15))/2, y+14), title, font=F(SANS,15), fill=FAINT)

def bubble(d, x, y, text, who, font, maxw=520, alpha=1.0):
    lines=[]; cur=""
    for wd in text.split():
        tt=(cur+" "+wd).strip()
        if d.textlength(tt,font=font)>maxw and cur: lines.append(cur); cur=wd
        else: cur=tt
    lines.append(cur)
    bw=max(d.textlength(l,font=font) for l in lines)+36; bh=len(lines)*28+22
    if who=="user": bx=x; fill=mix(PANE,SURF,alpha); tc=mix(PANE,TEXT,alpha); ol=LINE
    else: bx=x; fill=mix(PANE,(18,52,48),alpha); tc=mix(PANE,MINT,alpha); ol=mix(PANE,TEAL,0.4*alpha)
    d.rounded_rectangle((bx,y,bx+bw,y+bh),14,fill=fill,outline=ol,width=1)
    for i,l in enumerate(lines): d.text((bx+18,y+11+i*28), l, font=font, fill=tc)
    return bh

def caption(d, text):
    f=F(SANS,16); w=d.textlength(text,font=f); d.text((W/2-w/2, H-36), text, font=f, fill=FAINT)

# ---------- scenes: each returns an image for time t (seconds) ----------
def s_title(t):
    im,d=base(); orb(im, W//2, 250, 54, t, 0.25); d=ImageDraw.Draw(im)
    center(d,"Zoha",330,F(SERIF,150),TEXT)
    sub="A voice-first assistant that asks before acting."
    center(d,sub,520,F(SERIF_I,40),mix(GROUND,MUTED,ease((t-0.8)/0.8)))
    caption(d,"Illustrative demo, not a screen recording")
    return fade(im, ease(t/0.5))

def s_voice(t):
    im,d=base(); window(d,240,90,800,540)
    listening = t<2.0
    orb(im,640,210,38,t,0.6 if listening else 0.15); d=ImageDraw.Draw(im)
    window(d,240,90,800,540) if False else None
    d.text((W/2-d.textlength("Listening..." if listening else "Done",font=F(SANS,18))/2,272),"Listening..." if listening else "Done",font=F(SANS,18),fill=MUTED)
    txt=typed("Zoha, open Spotify",t,0.6,14)
    if txt: bubble(d,280,340,txt,"user",F(SANS,22))
    if t>2.6:
        a=ease((t-2.6)/0.4)
        d.rounded_rectangle((280,400,760,446),12,fill=mix(PANE,SURF,a),outline=LINE)
        d.text((304,411),"Opening Spotify",font=F(MONO,18),fill=mix(PANE,TEXT,a))
        cx,cy=725,423; d.line((cx-8,cy,cx-2,cy+7,cx+9,cy-8),fill=mix(PANE,TEAL,a),width=3)
    if t>3.4: bubble(d,280,470,"Done. Spotify is open.","zoha",F(SANS,22),alpha=ease((t-3.4)/0.4))
    caption(d,"Say it or type it. Both work.")
    return fade(im,min(ease(t/0.4),ease((6.0-t)/0.4)))

def s_ask(t):
    im,d=base(); window(d,240,90,800,540)
    y=166
    if t>0.3: y+=bubble(d,280,y,typed("Zoha, shut down the PC",t,0.3,18),"user",F(SANS,22))+14
    if t>2.0:
        y+=bubble(d,280,y,"Shut down now? Say yes to confirm.","zoha",F(SANS,22),alpha=ease((t-2.0)/0.4))+14
        # status pill
        a=ease((t-2.4)/0.4)
        d.rounded_rectangle((280,y,700,y+40),20,fill=mix(PANE,(60,30,26),a),outline=mix(PANE,CORAL,a))
        d.text((300,y+9),"Waiting for your answer. Nothing has happened.",font=F(SANS,16),fill=mix(PANE,CORAL,a)); y+=56
    if t>4.2: y+=bubble(d,280,y,typed("yes",t,4.2,6),"user",F(SANS,22))+14
    if t>5.2: y+=bubble(d,280,y,"Okay. Shutting down.","zoha",F(SANS,22),alpha=ease((t-5.2)/0.4))+14
    caption(d,"Shutdown, restart, sleep and site changes always need a clear yes.")
    return fade(im,min(ease(t/0.4),ease((7.0-t)/0.4)))

STEPS=["Write three drafts","Check the code","Test in a headless browser","Fix and polish"]
def s_web(t):
    im,d=base(); window(d,60,90,540,540,"Zoha")
    bubble(d,90,166,typed("Build a landing page for Sunrise Interiors",t,0.2,22),"user",F(SANS,20),maxw=440)
    y=270
    for i,s in enumerate(STEPS):
        st=1.6+i*1.3
        if t>st:
            a=ease((t-st)/0.3); done=t>st+1.1
            d.rounded_rectangle((90,y,570,y+46),12,fill=mix(PANE,SURF,a),outline=LINE)
            d.text((114,y+12),s,font=F(SANS,18),fill=mix(PANE,TEXT,a))
            cx,cy=540,y+23
            if done: d.line((cx-8,cy,cx-2,cy+7,cx+9,cy-8),fill=TEAL,width=3)
            else:
                ang=t*8; d.arc((cx-10,cy-10,cx+10,cy+10),math.degrees(ang),math.degrees(ang)+250,fill=TEAL,width=3)
        y+=58
    # preview page appears
    p=ease((t-6.4)/0.8)
    if p>0:
        x0,y0,w0,h0=640,110,580,500
        d.rounded_rectangle((x0,y0,x0+w0,y0+h0),14,fill=mix(GROUND,(244,238,228),p),outline=LINE)
        d.rectangle((x0,y0,x0+w0,y0+40),fill=mix(GROUND,(230,222,210),p))
        d.text((x0+24,y0+9),"sunrise-interiors.html",font=F(SANS,15),fill=mix(GROUND,(110,100,90),p))
        d.text((x0+40,y0+80),"Sunrise Interiors",font=F(SERIF,56),fill=mix(GROUND,(48,36,28),p))
        d.text((x0+40,y0+150),"Rooms that feel like morning.",font=F(SERIF_I,30),fill=mix(GROUND,(150,96,60),p))
        d.rounded_rectangle((x0+40,y0+210,x0+230,y0+256),23,fill=mix(GROUND,(48,36,28),p))
        d.text((x0+66,y0+222),"Book a visit",font=F(SANS,18),fill=mix(GROUND,(244,238,228),p))
        for i in range(3):
            cx0=x0+40+i*172; d.rounded_rectangle((cx0,y0+300,cx0+156,y0+450),10,fill=mix(GROUND,[(226,190,150),(200,170,140),(176,150,120)][i],p))
        if t>7.6:
            q=ease((t-7.6)/0.4); d.rounded_rectangle((x0+w0-170,y0+h0-52,x0+w0-14,y0+h0-14),19,fill=mix((244,238,228),TEAL,q))
            d.text((x0+w0-154,y0+h0-44),"Checked",font=F(SANS,17,),fill=mix((244,238,228),(8,14,13),q))
    caption(d,"Every page is linted and tested before she shows it.")
    return fade(im,min(ease(t/0.4),ease((9.0-t)/0.4)))

def s_end(t):
    im,d=base(); center(d,"Open source. Bring your own model.",190,F(SERIF,64),TEXT)
    items=["Apache-2.0","Plugins and skills are plain files","Windows first, ports welcome"]
    for i,s in enumerate(items):
        a=ease((t-0.8-i*0.5)/0.4); center(d,s,300+i*52,F(SANS,26),mix(GROUND,MUTED,a))
    a=ease((t-2.8)/0.5)
    d.rounded_rectangle((W/2-250,520,W/2+250,580),30,outline=mix(GROUND,TEAL,a),width=2)
    center(d,"github.com/zhessor/zoha",534,F(MONO,26),mix(GROUND,TEAL,a))
    return fade(im,min(ease(t/0.5),ease((5.0-t)/0.5)))

SCENES=[("title",4.0,s_title),("voice",6.0,s_voice),("ask",7.0,s_ask),("web",9.0,s_web),("end",5.0,s_end)]

def render(name,dur,fn,out):
    tmp=out+".part.mp4"
    p=subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","-",
        "-c:v","libx264","-crf","22","-preset","veryfast","-pix_fmt","yuv420p","-r",str(FPS),tmp],stdin=subprocess.PIPE)
    for i in range(int(dur*FPS)): p.stdin.write(fn(i/FPS).tobytes())
    p.stdin.close()
    if p.wait()!=0: raise SystemExit("ffmpeg failed")
    os.replace(tmp,out)

if __name__=="__main__":
    out=sys.argv[2]; os.makedirs(out,exist_ok=True)
    if len(sys.argv)>3 and sys.argv[3]=="stills":
        for n,dur,fn in SCENES:
            for k,tt in enumerate((dur*0.55,)): fn(tt).save(f"{out}/still_{n}.jpg",quality=92)
        sys.exit()
    files=[]
    for n,dur,fn in SCENES:
        f=f"{out}/{n}.mp4"; render(n,dur,fn,f); files.append(f)
    open(f"{out}/list.txt","w").write("".join(f"file '{f}'\n" for f in files))
    subprocess.check_call(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i",f"{out}/list.txt","-c","copy",f"{out}/zoha-demo.mp4"])
