#include <wayland-client.h>
#include <wayland-egl.h>
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <png.h>
#include "layer-shell.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <memory>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <vector>
#include <unistd.h>

static volatile sig_atomic_t running=1;
static volatile sig_atomic_t remap=0;
static void refresh(int){remap=1;}
static void stop(int){running=0;}
static void check(bool ok,const std::string& s){if(!ok)throw std::runtime_error(s);}
static const char* vertex=R"(
attribute vec2 pos;
varying vec2 uv;
void main(){uv=pos*.5+.5;gl_Position=vec4(pos,0.,1.);}
)";
static const char* scene=R"(
precision highp float;
varying vec2 uv;
uniform sampler2D figures;
uniform sampler2D tux;
uniform float angle;
uniform float aspect;
uniform float tuxScale;
uniform vec2 cellStep;
vec4 over(vec4 a,vec4 b){return vec4(mix(a.rgb,b.rgb,b.a),a.a+b.a*(1.-a.a));}
vec4 sampleScene(vec2 p,out float tuxMask){
 tuxMask=0.;
 // Contain the 16:9 composition on any output; never stretch the artwork.
 vec2 sc=vec2(max(1.,aspect/(16./9.)),max(1.,(16./9.)/aspect));
 p=(p-.5)*sc+.5;
 vec4 c=vec4(0.);
 if(p.x>=0.&&p.x<=1.&&p.y>=0.&&p.y<=1.)c=texture2D(figures,p);
 vec2 d=p-vec2(.5);
 float hx=.125*tuxScale;
 float cs=cos(angle),sn=sin(angle);
 // A shallow, textured silhouette volume, rather than a zero-thickness card.
 // Rays are intersected in local space so even the edge-on view has depth.
 vec2 screen=vec2(d.x/hx,d.y/(hx*(16./9.)));
 float pitch=.12,cp=cos(pitch),sp=sin(pitch),k=.38;
 vec3 ro=vec3(screen.x,screen.y*cp,-screen.y*sp);
 vec3 rd=vec3(k*screen.x,k*screen.y*cp+sp,-k*screen.y*sp+cp);
 ro=vec3(ro.x*cs-ro.z*sn,ro.y,ro.x*sn+ro.z*cs);
 rd=vec3(rd.x*cs-rd.z*sn,rd.y,rd.x*sn+rd.z*cs);
 vec3 bounds=vec3(1.,1138./960.,.14);
 vec3 safeDir=sign(rd+vec3(.0000001))*max(abs(rd),vec3(.000001));
 vec3 t0=(-bounds-ro)/safeDir,t1=(bounds-ro)/safeDir;
 vec3 nearT=min(t0,t1),farT=max(t0,t1);
 float entry=max(nearT.x,max(nearT.y,nearT.z));
 float leave=min(farT.x,min(farT.y,farT.z));
 if(leave>entry){
  for(int i=0;i<72;i++){
   float distance=mix(entry,leave,(float(i)+.1)/72.);
   vec3 q=ro+rd*distance;
   vec2 texcoord=vec2(q.x,q.y/bounds.y)*.5+.5;
   vec4 t=texture2D(tux,clamp(texcoord,vec2(.001),vec2(.999)));
   if(t.a>.22){
    float side=1.-smoothstep(.10,.135,abs(q.z));
    float light=.82+.15*cs-.10*sn;
    // The side is the material of the cut-out, not a squeezed copy of its face.
    float frontPaint=smoothstep(.12,.48,abs(cs))*(1.-side);
    float gold=step(.22,t.r-t.b)*step(.22,t.g);
    vec3 edgeColor=mix(vec3(.18,.20,.235),vec3(.55,.37,.08),gold);
    t.rgb=mix(edgeColor*.80,max(t.rgb,vec3(.14,.155,.18))*light,frontPaint);
    // Moving reflected light along the dark feathers reveals the turning edge.
    float rim=pow(max(0.,1.-abs(q.x+.50*sn)),10.)*.09*(.3+.7*abs(sn));
    t.rgb+=vec3(.62,.74,.90)*rim;
    t.a=min(1.,t.a*1.7);
    c=over(c,t);
    // Follow only the two eyes in texture space; leave head and beak unchanged.
    vec2 leftEye=(texcoord-vec2(.400,.202))/vec2(.055,.068);
    vec2 rightEye=(texcoord-vec2(.547,.200))/vec2(.068,.068);
    bool eye=min(dot(leftEye,leftEye),dot(rightEye,rightEye))<1.;
    tuxMask=eye?2.:1.;break;
   }
  }
 }
 return c;
}
void main(){
 vec2 p=vec2(uv.x,1.-uv.y);
 // Keep the original sampling for the composition, supersample the eyes only.
 vec2 dx=vec2(.0006,0.),dy=vec2(0.,.001);
 float m0,m1,m2,m3;
 vec4 c=(sampleScene(p+dx,m0)+sampleScene(p-dx,m1)+sampleScene(p+dy,m2)+sampleScene(p-dy,m3))*.25;
 float material=max(max(m0,m1),max(m2,m3));
 if(material>1.5){
  // Integrate the full character cell rather than a few nearly identical points.
  // The pupils then cross a cell smoothly instead of popping between black/white.
  c=vec4(0.);
  for(int y=0;y<4;y++){
   for(int x=0;x<4;x++){
    vec2 offset=(vec2(float(x),float(y))+.5)/4.-.5;
    float sampledMaterial;
    c+=sampleScene(p+offset*cellStep,sampledMaterial)/16.;
   }
  }
 }
 // RGBA8 packs three separated material bands plus fractional edge coverage.
 gl_FragColor=vec4(c.rgb,c.a*.24+material*.375);
}
)";
static const char* ascii=R"(
precision highp float;
varying vec2 uv;
uniform sampler2D cells;
uniform sampler2D atlas;
uniform vec2 grid;
uniform float elapsed;
void main(){
 vec2 id=floor(uv*grid);
 vec4 c=texture2D(cells,(id+.5)/grid);
 float material=step(.30,c.a)+step(.70,c.a);
 float tuxMask=step(.5,material);
 float eyeMask=step(1.5,material);
 c.a=clamp((c.a-material*.375)/.24,0.,1.);
 float lum=dot(c.rgb,vec3(.2126,.7152,.0722));
 float density=pow(clamp(lum,0.,1.),.63);
 float seed=fract(sin(dot(id,vec2(12.9898,78.233)))*43758.5453);
 float shimmer=(1.-eyeMask)*1.70*sin(elapsed*1.05+seed*6.28318);
 float glyph=clamp(density*14.+shimmer,0.,14.);
 // Eyes keep their source-dependent character density without timed shimmer.
 // No region is replaced by a uniform glyph pattern.
 vec2 local=fract(uv*grid);
 float inkA=texture2D(atlas,vec2((floor(glyph)+local.x)/15.,1.-local.y)).a;
 float inkB=texture2D(atlas,vec2((min(14.,floor(glyph)+1.)+local.x)/15.,1.-local.y)).a;
 float ink=mix(inkA,inkB,smoothstep(0.,1.,fract(glyph)));
 vec3 bg=vec3(.016,.021,.028);
 float wave=elapsed*.85+id.x*.055+id.y*.085;
 
 // Only breathe around each source color: no hue rotation or rainbow tint.
 float colorShimmer=1.-tuxMask;
 float saturation=1.+colorShimmer*.06*sin(wave+.8);
 vec3 sourceColor=mix(vec3(lum),c.rgb,saturation);
 vec3 color=clamp(sourceColor*(1.40+colorShimmer*.085*sin(wave))+.035,vec3(0.),vec3(1.));
 gl_FragColor=vec4(mix(bg,color,ink*c.a),1.);
}
)";
struct Options{
 std::string assets,output,snapshot;
 int columns=260,fps=30;
 bool listOutputs=false;
 float period=9,phase=0,tuxScale=.65,time=0;
};
struct App;
struct Output{
 App* app=nullptr;uint32_t id=0;std::string name;
 wl_output* output=nullptr;wl_surface* surface=nullptr;
 zwlr_layer_surface_v1* layer=nullptr;wl_callback* frame=nullptr;
 wl_egl_window* window=nullptr;EGLSurface egl=EGL_NO_SURFACE;
 int w=0,h=0;bool configured=false,ready=true,closed=false;
};
struct App{
 Options opt;
 wl_display* display=nullptr;wl_registry* registry=nullptr;wl_compositor* compositor=nullptr;
 zwlr_layer_shell_v1* shell=nullptr;
 std::vector<std::unique_ptr<Output>> outputs;
 EGLDisplay ed=EGL_NO_DISPLAY;EGLContext ctx=EGL_NO_CONTEXT;EGLConfig cfg{};EGLSurface offscreen=EGL_NO_SURFACE;
 GLuint sceneProgram=0,asciiProgram=0,fig=0,tuxTex=0,atlasTex=0,cellTex=0,fbo=0;
 int gw=0,gh=0;bool initialized=false;
 ~App();
 void init();void start(Output& o);void destroy(Output& o);void graphics();
 void paint(int w,int h,float angle,float time);void render(Output& o,float angle,float time);void snapshot();void loop();
};
static void geometry(void*,wl_output*,int32_t,int32_t,int32_t,int32_t,int32_t,const char*,const char*,int32_t){}
static void mode(void*,wl_output*,uint32_t,int32_t,int32_t,int32_t){}
static void done(void*,wl_output*){}
static void scale(void*,wl_output*,int32_t){}
static void name(void* data,wl_output*,const char* s){static_cast<Output*>(data)->name=s;}
static void desc(void*,wl_output*,const char*){}
static const wl_output_listener outputListener={geometry,mode,done,scale,name,desc};
static void configure(void* data,zwlr_layer_surface_v1* l,uint32_t serial,uint32_t w,uint32_t h){
 auto& o=*static_cast<Output*>(data);zwlr_layer_surface_v1_ack_configure(l,serial);
 o.w=w;o.h=h;o.configured=w>0&&h>0;o.ready=true;
 if(o.window)wl_egl_window_resize(o.window,w,h,0,0);
}
static void closed(void* data,zwlr_layer_surface_v1*){auto& o=*static_cast<Output*>(data);o.closed=true;}
static const zwlr_layer_surface_v1_listener layerListener={configure,closed};
static void frameDone(void* data,wl_callback* cb,uint32_t){
 auto& o=*static_cast<Output*>(data);wl_callback_destroy(cb);o.frame=nullptr;o.ready=true;
}
static const wl_callback_listener frameListener={frameDone};
static void global(void* data,wl_registry* r,uint32_t id,const char* iface,uint32_t ver){
 auto& a=*static_cast<App*>(data);
 if(!strcmp(iface,wl_compositor_interface.name))a.compositor=(wl_compositor*)wl_registry_bind(r,id,&wl_compositor_interface,std::min(ver,4u));
 else if(!strcmp(iface,zwlr_layer_shell_v1_interface.name))a.shell=(zwlr_layer_shell_v1*)wl_registry_bind(r,id,&zwlr_layer_shell_v1_interface,std::min(ver,4u));
 else if(!strcmp(iface,wl_output_interface.name)){
  auto o=std::make_unique<Output>();o->app=&a;o->id=id;
  o->output=(wl_output*)wl_registry_bind(r,id,&wl_output_interface,std::min(ver,4u));
  wl_output_add_listener(o->output,&outputListener,o.get());a.outputs.push_back(std::move(o));
 }
}
static void removed(void* data,wl_registry*,uint32_t id){
 auto& a=*static_cast<App*>(data);
 for(auto& o:a.outputs)if(o->id==id){a.destroy(*o);o->closed=true;}
}
static const wl_registry_listener registryListener={global,removed};
static GLuint shader(GLenum type,const char* source){
 GLuint s=glCreateShader(type);glShaderSource(s,1,&source,nullptr);glCompileShader(s);
 GLint ok;glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
 if(!ok){char log[4096];glGetShaderInfoLog(s,sizeof(log),nullptr,log);throw std::runtime_error(log);}return s;
}
static GLuint program(const char* fragment){
 GLuint v=shader(GL_VERTEX_SHADER,vertex),f=shader(GL_FRAGMENT_SHADER,fragment),p=glCreateProgram();
 glAttachShader(p,v);glAttachShader(p,f);glBindAttribLocation(p,0,"pos");glLinkProgram(p);
 glDeleteShader(v);glDeleteShader(f);GLint ok;glGetProgramiv(p,GL_LINK_STATUS,&ok);
 if(!ok){char log[4096];glGetProgramInfoLog(p,sizeof(log),nullptr,log);throw std::runtime_error(log);}return p;
}
static GLuint texture(const std::string& path){
 png_image im{};im.version=PNG_IMAGE_VERSION;
 check(png_image_begin_read_from_file(&im,path.c_str()),"Cannot load "+path);
 im.format=PNG_FORMAT_RGBA;std::vector<unsigned char> pixels(PNG_IMAGE_SIZE(im));
 check(png_image_finish_read(&im,nullptr,pixels.data(),0,nullptr),"Invalid PNG "+path);
 GLuint t;glGenTextures(1,&t);glBindTexture(GL_TEXTURE_2D,t);
 glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,im.width,im.height,0,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
 glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
 glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
 png_image_free(&im);return t;
}
static void unit(GLuint p,const char* uniform,int n,GLuint t){
 glActiveTexture(GL_TEXTURE0+n);glBindTexture(GL_TEXTURE_2D,t);glUniform1i(glGetUniformLocation(p,uniform),n);
}
static void quad(){
 static const GLfloat vertices[]={-1,-1,1,-1,-1,1,1,1};
 glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,vertices);glEnableVertexAttribArray(0);glDrawArrays(GL_TRIANGLE_STRIP,0,4);
}
void App::init(){
 display=wl_display_connect(nullptr);check(display,"Cannot connect to Wayland session");
 registry=wl_display_get_registry(display);wl_registry_add_listener(registry,&registryListener,this);
 check(wl_display_roundtrip(display)>=0,"Wayland registry failed");
 check(wl_display_roundtrip(display)>=0,"Wayland outputs failed");
 check(compositor&&shell,"This Wayland compositor does not provide wlr-layer-shell. Try Hyprland, Sway or niri; stock GNOME and X11 are not supported.");
 if(opt.listOutputs){for(const auto& o:outputs)if(!o->name.empty())std::cout<<o->name<<"\n";return;}
 check(!outputs.empty(),"No Wayland outputs available");
 if(!opt.output.empty()){
  std::string requested=","+opt.output+",";bool matched=false;
  for(const auto& o:outputs)if(!o->name.empty()&&requested.find(","+o->name+",")!=std::string::npos)matched=true;
  check(matched,"None of the requested monitors is connected. Use --list-outputs to list connectors.");
 }
 ed=eglGetDisplay((EGLNativeDisplayType)display);check(ed!=EGL_NO_DISPLAY,"eglGetDisplay failed");
 check(eglInitialize(ed,nullptr,nullptr),"eglInitialize failed");eglBindAPI(EGL_OPENGL_ES_API);
 const EGLint attrs[]={EGL_SURFACE_TYPE,EGL_WINDOW_BIT|EGL_PBUFFER_BIT,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES2_BIT,EGL_NONE};
 EGLint n=0;check(eglChooseConfig(ed,attrs,&cfg,1,&n)&&n,"No EGL configuration");
 const EGLint ca[]={EGL_CONTEXT_CLIENT_VERSION,2,EGL_NONE};ctx=eglCreateContext(ed,cfg,EGL_NO_CONTEXT,ca);
 check(ctx!=EGL_NO_CONTEXT,"eglCreateContext failed");
 const EGLint pa[]={EGL_WIDTH,1920,EGL_HEIGHT,1080,EGL_NONE};offscreen=eglCreatePbufferSurface(ed,cfg,pa);
 check(offscreen!=EGL_NO_SURFACE,"EGL offscreen surface failed");
 check(eglMakeCurrent(ed,offscreen,offscreen,ctx),"EGL context failed");
 std::cout<<"Renderer: "<<glGetString(GL_RENDERER)<<"; "<<opt.columns<<" columns, "<<opt.fps<<" fps\n";
 graphics();initialized=true;
}
void App::graphics(){
 sceneProgram=program(scene);asciiProgram=program(ascii);
 fig=texture(opt.assets+"/figures.png");tuxTex=texture(opt.assets+"/tux.png");atlasTex=texture(opt.assets+"/glyphs.png");
 glGenTextures(1,&cellTex);glGenFramebuffers(1,&fbo);
 glDisable(GL_DEPTH_TEST);glDisable(GL_BLEND);
}
void App::start(Output& o){
 if(o.closed||o.surface||o.name.empty())return;
 if(!opt.output.empty()){
  std::string list=","+opt.output+",";
  if(list.find(","+o.name+",")==std::string::npos)return;
 }
 o.surface=wl_compositor_create_surface(compositor);
 auto region=wl_compositor_create_region(compositor);wl_surface_set_input_region(o.surface,region);wl_region_destroy(region);
 o.layer=zwlr_layer_shell_v1_get_layer_surface(shell,o.surface,o.output,ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND,"creation-of-tux-wallpaper");
 zwlr_layer_surface_v1_add_listener(o.layer,&layerListener,&o);
 zwlr_layer_surface_v1_set_anchor(o.layer,15);zwlr_layer_surface_v1_set_size(o.layer,0,0);
 zwlr_layer_surface_v1_set_exclusive_zone(o.layer,-1);
 zwlr_layer_surface_v1_set_keyboard_interactivity(o.layer,ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE);
 wl_surface_commit(o.surface);
 std::cout<<"Wallpaper surface: "<<o.name<<"\n";
}
void App::paint(int w,int h,float angle,float time){
 int cols=std::min(opt.columns,std::max(40,w/4));
 int rows=std::max(10,int(std::lround(double(cols)*h/w*14./26.)));
 if(gw!=cols||gh!=rows){
  gw=cols;gh=rows;glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,cellTex);
  glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,gw,gh,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
  glBindFramebuffer(GL_FRAMEBUFFER,fbo);glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,cellTex,0);
  check(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"ASCII framebuffer incomplete");
 }
 glBindFramebuffer(GL_FRAMEBUFFER,fbo);glViewport(0,0,gw,gh);glUseProgram(sceneProgram);
 unit(sceneProgram,"figures",0,fig);unit(sceneProgram,"tux",1,tuxTex);
 glUniform1f(glGetUniformLocation(sceneProgram,"angle"),angle);
 glUniform1f(glGetUniformLocation(sceneProgram,"aspect"),float(w)/h);
 glUniform1f(glGetUniformLocation(sceneProgram,"tuxScale"),opt.tuxScale);
 glUniform2f(glGetUniformLocation(sceneProgram,"cellStep"),1.f/gw,1.f/gh);quad();
 glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,w,h);glUseProgram(asciiProgram);
 unit(asciiProgram,"cells",0,cellTex);unit(asciiProgram,"atlas",1,atlasTex);
 glUniform2f(glGetUniformLocation(asciiProgram,"grid"),gw,gh);
 glUniform1f(glGetUniformLocation(asciiProgram,"elapsed"),time);quad();
 check(glGetError()==GL_NO_ERROR,"OpenGL render error");
}
void App::render(Output& o,float angle,float time){
 if(!o.configured||o.closed||!o.ready)return;
 if(!o.window){
  o.window=wl_egl_window_create(o.surface,o.w,o.h);check(o.window,"Wayland EGL window failed");
  o.egl=eglCreateWindowSurface(ed,cfg,(EGLNativeWindowType)o.window,nullptr);
  check(o.egl!=EGL_NO_SURFACE,"EGL window surface failed");
 }
 check(eglMakeCurrent(ed,o.egl,o.egl,ctx),"Cannot activate output context");eglSwapInterval(ed,0);
 paint(o.w,o.h,angle,time);
 o.frame=wl_surface_frame(o.surface);wl_callback_add_listener(o.frame,&frameListener,&o);o.ready=false;
 check(eglSwapBuffers(ed,o.egl),"EGL swap failed");
}
void App::snapshot(){
 paint(1920,1080,opt.phase*float(M_PI)/180.f,opt.time);
 std::vector<unsigned char> p(1920*1080*4),flipped(p.size());glReadPixels(0,0,1920,1080,GL_RGBA,GL_UNSIGNED_BYTE,p.data());
 for(int y=0;y<1080;y++)memcpy(flipped.data()+y*1920*4,p.data()+(1079-y)*1920*4,1920*4);
 png_image im{};im.version=PNG_IMAGE_VERSION;im.width=1920;im.height=1080;im.format=PNG_FORMAT_RGBA;
 check(png_image_write_to_file(&im,opt.snapshot.c_str(),0,flipped.data(),0,nullptr),"Cannot write snapshot");
 std::cout<<"Snapshot: "<<opt.snapshot<<"\n";
}
void App::loop(){
 using Clock=std::chrono::steady_clock;const auto begin=Clock::now();
 auto next=begin;const auto step=std::chrono::microseconds(1000000/opt.fps);
 while(running){
  if(remap){remap=0;for(auto& o:outputs)destroy(*o);}
  for(auto& o:outputs){if(o->closed&&o->surface)destroy(*o);else start(*o);}
  const auto now=Clock::now();
  if(now>=next){
   float t=std::chrono::duration<float>(now-begin).count();
   for(auto& o:outputs)render(*o,-t*2.f*float(M_PI)/opt.period+opt.phase*float(M_PI)/180.f,t);
   next=Clock::now()+step;
  }
  while(wl_display_prepare_read(display)!=0)check(wl_display_dispatch_pending(display)>=0,"Wayland disconnected");
  wl_display_flush(display);
  int ms=std::max(1,int(std::chrono::duration_cast<std::chrono::milliseconds>(next-Clock::now()).count()));
  pollfd fd{wl_display_get_fd(display),POLLIN,0};int rc=poll(&fd,1,ms);
  if(rc>0&&(fd.revents&POLLIN))check(wl_display_read_events(display)>=0,"Wayland read failed");
  else wl_display_cancel_read(display);
  if(rc>0&&(fd.revents&(POLLHUP|POLLERR)))throw std::runtime_error("Wayland connection closed");
  check(wl_display_dispatch_pending(display)>=0,"Wayland dispatch failed");
 }
}
void App::destroy(Output& o){
 if(o.frame){wl_callback_destroy(o.frame);o.frame=nullptr;}
 if(o.egl!=EGL_NO_SURFACE){eglMakeCurrent(ed,offscreen,offscreen,ctx);eglDestroySurface(ed,o.egl);o.egl=EGL_NO_SURFACE;}
 if(o.window){wl_egl_window_destroy(o.window);o.window=nullptr;}
 if(o.layer){zwlr_layer_surface_v1_destroy(o.layer);o.layer=nullptr;}
 if(o.surface){wl_surface_destroy(o.surface);o.surface=nullptr;}
 o.configured=false;
}
App::~App(){
 for(auto& o:outputs)destroy(*o);
 if(ed!=EGL_NO_DISPLAY){
  if(ctx!=EGL_NO_CONTEXT&&offscreen!=EGL_NO_SURFACE){eglMakeCurrent(ed,offscreen,offscreen,ctx);
   glDeleteTextures(1,&fig);glDeleteTextures(1,&tuxTex);glDeleteTextures(1,&atlasTex);glDeleteTextures(1,&cellTex);glDeleteFramebuffers(1,&fbo);
   glDeleteProgram(sceneProgram);glDeleteProgram(asciiProgram);}
  eglMakeCurrent(ed,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT);
  if(offscreen!=EGL_NO_SURFACE)eglDestroySurface(ed,offscreen);
  if(ctx!=EGL_NO_CONTEXT)eglDestroyContext(ed,ctx);
  eglTerminate(ed);
 }
 for(auto& o:outputs)if(o->output)wl_output_destroy(o->output);
 if(shell)zwlr_layer_shell_v1_destroy(shell);
 if(compositor)wl_compositor_destroy(compositor);
 if(registry)wl_registry_destroy(registry);
 if(display)wl_display_disconnect(display);
}
int main(int argc,char** argv){
 try{
  App a;a.opt.assets=(std::filesystem::canonical("/proc/self/exe").parent_path().parent_path()/"assets").string();
  for(int i=1;i<argc;i++){
   std::string x=argv[i];auto value=[&](){check(i+1<argc,"Missing value for "+x);return std::string(argv[++i]);};
   if(x=="--list-outputs")a.opt.listOutputs=true;
   else if(x=="--version"){std::cout<<"Creation of Tux 0.1.0\n";return 0;}
   else if(x=="--assets")a.opt.assets=value();else if(x=="--output")a.opt.output=value();else if(x=="--snapshot")a.opt.snapshot=value();
   else if(x=="--columns")a.opt.columns=std::stoi(value());else if(x=="--fps")a.opt.fps=std::stoi(value());
   else if(x=="--period")a.opt.period=std::stof(value());else if(x=="--phase")a.opt.phase=std::stof(value());
   else if(x=="--tux-scale")a.opt.tuxScale=std::stof(value());
   else if(x=="--time")a.opt.time=std::stof(value());
   else if(x=="--help"){std::cout<<"Creation of Tux — native animated ASCII wallpaper for Wayland\n--columns 260 --fps 30 --period 9 --tux-scale 0.65\n--output DP-1,eDP-1 (default: all)\n--list-outputs | --version\n--snapshot /absolute/path.png --phase 0 --time 0\n";return 0;}
   else throw std::runtime_error("Unknown option "+x);
  }
  check(a.opt.columns>=60&&a.opt.columns<=600&&a.opt.fps>=1&&a.opt.fps<=120&&a.opt.period>=2&&std::isfinite(a.opt.period)&&a.opt.tuxScale>=.1&&a.opt.tuxScale<=1.5&&std::isfinite(a.opt.phase)&&std::isfinite(a.opt.time),"Invalid rendering options");
  signal(SIGINT,stop);signal(SIGTERM,stop);signal(SIGUSR1,refresh);std::cout.setf(std::ios::unitbuf);
  a.init();if(a.opt.listOutputs)return 0;if(!a.opt.snapshot.empty())a.snapshot();else a.loop();
 }catch(const std::exception& e){std::cerr<<"Creation ASCII: "<<e.what()<<"\n";return 1;}return 0;
}
