# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import bpy, bmesh, os, datetime, shlex, sys, math, pickle
from mathutils import Vector
from subprocess import Popen, PIPE, STDOUT
from numpy import array, where, in1d, transpose, savetxt, int8, float16, float32, float64, digitize, zeros, choose, inner, average, amax, amin, concatenate
from numpy import sum as nsum
from numpy import max as nmax
from numpy import min as nmin
from numpy import mean as nmean
from numpy import append as nappend
from .vi_func import vertarea, logentry, ct2RGB, clearlayers, chunks, selobj, solarPosition, sunapply
from .vi_dicts import res2unit, unit2res

def sunposlivi(scene, skynode, frames, sun, stime):
    svp = scene.vi_params
    
    if skynode['skynum'] < 3 or (skynode.skyprog == '1' and skynode.epsilon > 1): 
        times = [stime + frame*datetime.timedelta(seconds = 3600*skynode.interval) for frame in range(len(frames))]  
        solposs = [solarPosition(t.timetuple()[7], t.hour + (t.minute)*0.016666, svp.latitude, svp.longitude) for t in times]
        beamvals = [(0, 3)[solposs[t][0] > 0] for t in range(len(times))] if skynode['skynum'] < 2  or (skynode.skyprog == '1' and skynode.epsilon > 1) else [0 for t in range(len(times))]
        skyvals = [5 for t in range(len(times))]
        
    elif skynode['skynum'] == 3 and skynode.skyprog == '0': 
        times = [datetime.datetime(2015, 3, 20, 12, 0)]
        solposs = [solarPosition(t.timetuple()[7], t.hour + (t.minute)*0.016666, 0, 0) for t in times]
        beamvals = [0 for t in range(len(times))]
        skyvals = [5 for t in range(len(times))]
       
    shaddict = {'0': 0.01, '1': 2, '2': 5, '3': 5}
    values = list(zip([shaddict[str(skynode['skynum'])] for t in range(len(times))], beamvals, skyvals))
    sunapply(scene, sun, values, solposs, frames, skynode.sdist)
    
def face_bsdf(o, m, mname, f):  
    if m.vi_params.get('bsdf'):
        uv = '{0[0]:.4f} {0[1]:.4f} {0[2]:.4f}'.format(m.vi_params.li_bsdf_up)
        #MGF geometry does not work (black inner face)
        # if m.vi_params.li_bsdf_proxy_depth and m.vi_params['bsdf'].get('proxied'):
        #     trans = f.calc_center_median() - Vector([float(p) for p in m.vi_params['bsdf']['pos'].split()])
        #     rot = f.normal.rotation_difference(Vector((0, 0, 1))).to_euler()
        #     rot_deg = [180*r/math.pi for r in (rot.x, rot.y, rot.z)]
        #     print(rot_deg)
        #     upv = Vector((0, 1, 0))
        #     upv.rotate(rot)
        #     rot2 = upv.rotation_difference(Vector((0, 0, 1))).to_euler() 
        #     rot2_deg = [180*r/math.pi for r in (rot2.x, rot2.y, rot2.z)]
        #     print('rot2', upv, rot2_deg)
        #     rot3 = f.normal.rotation_difference(Vector([-float(p) for p in m.vi_params['bsdf']['normal'].split()])).to_euler()
        #     rot3_deg = [180*r/math.pi for r in (rot3.x, rot3.y, rot3.z)]
        #     print(f.normal, m.vi_params['bsdf']['normal'])
        #     print(rot3_deg)
        #     pkgbsdfrun = Popen(shlex.split("pkgBSDF -s {}".format(os.path.join(bpy.context.scene.vi_params['viparams']['newdir'], 'bsdfs', '{}.xml'.format(m.name)))), stdout = PIPE)
        #     xformrun = Popen(shlex.split("xform -rx {0[0]} -ry {0[1]} -rz {0[2]} -t {1[0]} {1[1]} {1[2]}".format(rot_deg, trans)), stdin = pkgbsdfrun.stdout, stdout = PIPE)
        #     radentry = ''.join([line.decode() for line in xformrun.stdout])
        #     radentry = radentry.replace('m_{}_f'.format(m.name), mname)
        #     radentry = radentry.replace(' {}.xml '.format(m.name), ' {} '.format(os.path.join(bpy.context.scene.vi_params['viparams']['newdir'], 'bsdfs', '{}.xml'.format(m.name))))
        # else:
        radentry = 'void BSDF {0}\n6 {3} {1} {2} .\n0\n0\n\n'.format(mname,  
            os.path.join(bpy.context.scene.vi_params['viparams']['newdir'], 'bsdfs', 
            '{}.xml'.format(m.name)), uv, m.vi_params.li_bsdf_proxy_depth)
        return radentry
    else:
        return ''

def rtpoints(self, bm, offset, frame):    
    geom = bm.verts if self['cpoint'] == '1' else bm.faces 
    cindex = geom.layers.int['cindex']
    rt = geom.layers.string['rt{}'.format(frame)]

    for gp in geom:
        gp[cindex] = 0 
        
    geom.ensure_lookup_table()
    resfaces = [face for face in bm.faces if self.id_data.data.materials[face.material_index].vi_params.mattype == '1']
    self['cfaces'] = [face.index for face in resfaces]
       
    if self['cpoint'] == '0': 
        gpoints = resfaces
        gpcos =  [gp.calc_center_median() for gp in gpoints]
        self['cverts'], self['lisenseareas'][frame] = [], [f.calc_area() for f in gpoints]       

    elif self['cpoint'] == '1': 
        gis = sorted(set([item.index for sublist in [face.verts[:] for face in resfaces] for item in sublist]))
        gpoints = [geom[gi] for gi in gis]
        gpcos = [gp.co for gp in gpoints]
        self['cverts'], self['lisenseareas'][frame] = gp.index, [vertarea(bm, gp) for gp in gpoints]    
    
    for g, gp in enumerate(gpoints):
        gp[rt] = '{0[0]:.4f} {0[1]:.4f} {0[2]:.4f} {1[0]:.4f} {1[1]:.4f} {1[2]:.4f}'.format([gpcos[g][i] + offset * gp.normal.normalized()[i] for i in range(3)], gp.normal[:]).encode('utf-8')
        gp[cindex] = g + 1
        
    self['rtpnum'] = g + 1

def setscenelivivals(scene):
    svp = scene.vi_params
    svp['liparams']['maxres'], svp['liparams']['minres'], svp['liparams']['avres'] = {}, {}, {}

    if svp.li_disp_menu and svp.li_disp_menu != 'None':
        res = svp.li_disp_menu
    else:
        res = unit2res[svp['liparams']['unit']]

    olist = [o for o in bpy.data.objects if o.vi_params.vi_type_string == 'LiVi Calc']

    for frame in range(svp['liparams']['fs'], svp['liparams']['fe'] + 1):
        svp['liparams']['maxres'][str(frame)] = max([o.vi_params['omax']['{}{}'.format(res, frame)] for o in olist])
        svp['liparams']['minres'][str(frame)] = min([o.vi_params['omin']['{}{}'.format(res, frame)] for o in olist])
        svp['liparams']['avres'][str(frame)] = sum([o.vi_params['oave']['{}{}'.format(res, frame)] for o in olist])/len([o.vi_params['oave']['{}{}'.format(res, frame)] for o in olist])

    svp.vi_leg_max = max(svp['liparams']['maxres'].values())
    svp.vi_leg_min = min(svp['liparams']['minres'].values())
    
def validradparams(params):
    valids = ('-ps', '-pt', '-pj', '-dj', '-ds', '-dt', '-dc', '-dr', '-dp', '-ss', '-st', '-sj', '-ab', 
              '-av', '-aa',	'-ar', '-ad', '-as', '-lr', '-lw', '-u+')
    for p, param in enumerate(params.split()):
        if not p%2 and (param not in valids):
            return 0
        elif  p%2:
            try: float(param)
            except: return 0   
    return 1    
        
def radmat(self, scene):
    svp = scene.vi_params
    radname = self.id_data.name.replace(" ", "_")
    radname = radname.replace(",", "")
    self['radname'] = radname
    radtex = ''
    mod = 'void' 
    
    if self.mattype == '0' and self.radmatmenu in ('0', '1', '2', '3', '6') and self.radtex:
        try:
            fd, fn = os.path.dirname(bpy.data.filepath), os.path.splitext(os.path.basename(bpy.data.filepath))[0]
            nd = os.path.join(fd, fn)
            svp['liparams']['texfilebase'] = os.path.join(nd, 'textures')
            teximage = self.id_data.node_tree.nodes['Material Output'].inputs['Surface'].links[0].from_node.inputs['Color'].links[0].from_node.image
            teximageloc = os.path.join(svp['liparams']['texfilebase'],'{}.hdr'.format(radname))
            off = scene.render.image_settings.file_format 
            scene.render.image_settings.file_format = 'HDR'
            teximage.save_render(teximageloc)
            scene.render.image_settings.file_format = off
            (w, h) = teximage.size
            ar = ('*{}'.format(w/h), '') if w >= h else ('', '*{}'.format(h/w))
            radtex = 'void colorpict {}_tex\n7 red green blue {} . frac(Lu){} frac(Lv){}\n0\n0\n\n'.format(radname, '{}'.format(teximageloc), ar[0], ar[1])
            mod = '{}_tex'.format(radname)
            
            try:
                if self.radnorm: 
                    normmapnode = self.id_data.node_tree.nodes['Material Output'].inputs['Surface'].links[0].from_node.inputs['Normal'].links[0].from_node
                    normimage = normmapnode.inputs['Color'].links[0].from_node.image
                    normpixels = zeros(normimage.size[0] * normimage.size[1] * 4, dtype='float32')
                    normimage.pixels.foreach_get(normpixels)
                    header = '2\n0 1 {}\n0 1 {}\n'.format(normimage.size[1], normimage.size[0])
                    xdat = -1 + 2 * normpixels[:][0::4].reshape(normimage.size[0], normimage.size[1])
                    ydat = -1 + 2 * normpixels[:][1::4].reshape(normimage.size[0], normimage.size[1])# if self.gup == '0' else 1 - 2 * array(normimage.pixels[:][1::4]).reshape(normimage.size[0], normimage.size[1])
                    savetxt(os.path.join(svp['liparams']['texfilebase'],'{}.ddx'.format(radname)), xdat, fmt='%.2f', header = header, comments='')
                    savetxt(os.path.join(svp['liparams']['texfilebase'],'{}.ddy'.format(radname)), ydat, fmt='%.2f', header = header, comments='')                  
                    radtex += "{0}_tex texdata {0}_norm\n9 ddx ddy ddz {1}.ddx {1}.ddy {1}.ddy nm.cal frac(Lv){2} frac(Lu){3}\n0\n7 {4} {5[0]} {5[1]} {5[2]} {6[0]} {6[1]} {6[2]}\n\n".format(radname, 
                               os.path.join(svp['viparams']['newdir'], 'textures', radname), ar[1], ar[1], normmapnode.inputs[0].default_value, self.nu, self.nside)
                    mod = '{}_norm'.format(radname)
                    
            except Exception as e:
                logentry('Problem with normal export {}'.format(e))
                
        except Exception as e:
            logentry('Problem with texture export {}'.format(e))
    if self.radtransmenu == '0':
        tn = self.radtrans
    else:
        tn = (((0.8402528435 + 0.0072522239 * self.radtransmit * self.radtransmit) ** 0.5) - 0.9166530661)/(0.0036261119 * self.radtransmit)     
        tn = (tn, tn, tn)

    radentry = '# ' + ('plastic', 'glass', 'dielectric', 'translucent', 'mirror', 'light', 'metal', 'antimatter', 'bsdf', 'custom')[int(self.radmatmenu)] + ' material\n' + \
            '{} {} {}\n'.format(mod, ('plastic', 'glass', 'dielectric', 'trans', 'mirror', 'light', 'metal', 'antimatter', 'bsdf', 'custom')[int(self.radmatmenu)], radname) + \
           {'0': '0\n0\n5 {0[0]:.3f} {0[1]:.3f} {0[2]:.3f} {1:.3f} {2:.3f}\n'.format(self.radcolour, self.radspec, self.radrough), 
            '1': '0\n0\n3 {0[0]:.3f} {0[1]:.3f} {0[2]:.3f}\n'.format(tn), 
            '2': '0\n0\n5 {0[0]:.3f} {0[1]:.3f} {0[2]:.3f} {1:.3f} 0\n'.format(self.radtrans, self.radior),
            '3': '0\n0\n7 {0[0]:.3f} {0[1]:.3f} {0[2]:.3f} {1:.3f} {2:.3f} {3:.3f} {4:.3f}\n'.format(self.radcolour, self.radspec, self.radrough, self.radtransdiff, self.radtranspec), 
            '4': '0\n0\n3 {0[0]:.3f} {0[1]:.3f} {0[2]:.3f}\n'.format(self.radcolour),
            '5': '0\n0\n3 {0[0]:.3f} {0[1]:.3f} {0[2]:.3f}\n'.format([c * self.radintensity for c in (self.radcolour, ct2RGB(self.radct))[self.radcolmenu == '1']]), 
            '6': '0\n0\n5 {0[0]:.3f} {0[1]:.3f} {0[2]:.3f} {1:.3f} {2:.3f}\n'.format(self.radcolour, self.radspec, self.radrough), 
            '7': '1 void\n0\n0\n', '8': '1 void\n0\n0\n', '9': '1 void\n0\n0\n'}[self.radmatmenu] + '\n'
    
    if self.radmatmenu == '8':
        radentry = ''

    elif self.radmatmenu == '9':
        radentry = bpy.data.texts[self.radfile].as_string()+'\n\n' if self.radfile in [t.name for t in bpy.data.texts] else '# dummy material\nvoid plastic {}\n0\n0\n5 0.8 0.8 0.8 0.1 0.1\n\n'.format(radname)
                        
    self['radentry'] = radtex + radentry
    return(radtex + radentry)    
    
def cbdmmtx(self, scene, locnode, export_op):
    svp = scene.vi_params
    res = (1, 2, 4)[self.cbdm_res - 1]
    os.chdir(svp['viparams']['newdir'])  
    (csh, ceh) = (self.cbdm_start_hour, self.cbdm_end_hour) if not self.ay or (self.cbanalysismenu == '2' and self.leed4) else (1, 24)  
    (sdoy, edoy) =  (self.sdoy, self.edoy) if not self.ay else (1, 365)
    
    if self['epwbase'][1] in (".epw", ".EPW"):
        with open(locnode.weather, "r") as epwfile:
            epwlines = epwfile.readlines()
            self['epwyear'] = epwlines[8].split(",")[0]

        Popen(("epw2wea", locnode.weather, "{}.wea".format(os.path.join(svp['viparams']['newdir'], self['epwbase'][0])))).wait()
        
        with open("{}.wea".format(os.path.join(svp['viparams']['newdir'], self['epwbase'][0])), 'r') as weafile:
            weadata = weafile.readlines()
            
        with open("{}.wea".format(os.path.join(svp['viparams']['newdir'], self['epwbase'][0])), 'w') as weafile:
            for line in weadata:
                ls = line.split()
                if len(ls) != 5:
                    weafile.write(line)
                elif csh <= float(ls[2]) <= ceh and sdoy <= datetime.datetime(svp['year'], int(ls[0]), int(ls[1])).timetuple().tm_yday <= edoy and datetime.datetime(svp['year'], int(ls[0]), int(ls[1])).weekday() <= (6, 4)[self.weekdays]:
                    weafile.write(line)
                
        gdmcmd = ("gendaymtx -m {} {} {}".format(res, ('-O0', '-O1')[self['watts']], 
                  "{0}.wea".format(os.path.join(svp['viparams']['newdir'], self['epwbase'][0]))))

        with open("{}.mtx".format(os.path.join(svp['viparams']['newdir'], self['epwbase'][0])), 'w') as mtxfile:
            Popen(gdmcmd.split(), stdout = mtxfile, stderr=STDOUT).communicate()
        with open("{}-whitesky.oct".format(svp['viparams']['filebase']), 'w') as wsfile:
            oconvcmd = "oconv -w -"
            Popen(shlex.split(oconvcmd), stdin = PIPE, stdout = wsfile).communicate(input = self['whitesky'].encode(sys.getfilesystemencoding()))
        return "{}.mtx".format(os.path.join(svp['viparams']['newdir'], self['epwbase'][0]))
    else:
        export_op.report({'ERROR'}, "Not a valid EPW file")
        return ''
    
def cbdmhdr(node, scene):
    patches = (146, 578, 2306)[node.cbdm_res - 1]    
    svp = scene.vi_params
    targethdr = os.path.join(svp['viparams']['newdir'], node['epwbase'][0]+"{}.hdr".format(('l', 'w')[node['watts']]))
    latlonghdr = os.path.join(svp['viparams']['newdir'], node['epwbase'][0]+"{}p.hdr".format(('l', 'w')[node['watts']]))
    skyentry = hdrsky(node.hdrname, '1', 0, 1000) if node.sourcemenu == '1' and  node.cbanalysismenu == '0' else hdrsky(targethdr, '1', 0, 1000)

    if node.sourcemenu != '1' or node.cbanalysismenu == '2':
        vecvals, vals = mtx2vals(open(node['mtxfile'], 'r').readlines(), datetime.datetime(svp['year'], 1, 1).weekday(), node, node.times)
        pcombfiles = ''.join(["{} ".format(os.path.join(svp['viparams']['newdir'], 'ps{}.hdr'.format(i))) for i in range(patches)])
        vwcmd = 'vwrays -ff -x 600 -y 600 -vta -vp 0 0 0 -vd 0 1 0 -vu 0 0 1 -vh 360 -vv 360 -vo 0 -va 0 -vs 0 -vl 0'
        rcontribcmd = 'rcontrib -bn {} -fo -ab 0 -ad 1 -n {} -ffc -x 600 -y 600 -ld- -V+ -f reinhart{}.cal -b rbin -o "{}" -m sky_glow "{}-whitesky.oct"'.format(patches, svp['viparams']['nproc'], 
                                                           node.cbdm_res,
                                                           os.path.join(svp['viparams']['newdir'], 'p%d.hdr'), 
                                                           os.path.join(svp['viparams']['newdir'], 
                                                                        svp['viparams']['filename']))

        vwrun = Popen(shlex.split(vwcmd), stdout = PIPE)
        rcrun = Popen(shlex.split(rcontribcmd), stderr = PIPE, stdin = vwrun.stdout)

        for line in rcrun.stderr:
            logentry('HDR generation error: {}'.format(line))
    
        for j in range(patches):
            with open(os.path.join(svp['viparams']['newdir'], "ps{}.hdr".format(j)), 'w') as psfile:
                Popen(shlex.split('pcomb -s {} "{}"'.format(vals[j], os.path.join(svp['viparams']['newdir'], 'p{}.hdr'.format(j)))), stdout = psfile).wait()
        
        with open(targethdr, 'w') as epwhdr:
            if sys.platform == 'win32':
                Popen("pcomb -h {}".format(pcombfiles), stdout = epwhdr).wait()
            else:
                Popen(shlex.split('pcomb -h {}'.format(pcombfiles)), stdout = epwhdr).wait()
        
        [os.remove(os.path.join(svp['viparams']['newdir'], 'p{}.hdr'.format(i))) for i in range (patches)]
        [os.remove(os.path.join(svp['viparams']['newdir'], 'ps{}.hdr'.format(i))) for i in range (patches)]
        node.hdrname = targethdr
    
        if node.hdr:
            with open('{}.oct'.format(os.path.join(svp['viparams']['newdir'], node['epwbase'][0])), 'w') as hdroct:
                Popen(shlex.split('oconv -w - '), stdin = PIPE, stdout=hdroct, stderr=STDOUT).communicate(input = skyentry.encode(sys.getfilesystemencoding()))

            cntrun = Popen('cnt 750 1500'.split(), stdout = PIPE)
            rccmd = 'rcalc -f "{}" -e XD=1500;YD=750;inXD=0.000666;inYD=0.001333'.format(os.path.join(svp.vipath, 'RadFiles', 'lib', 'latlong.cal'))
            logentry('Running rcalc: {}'.format(rccmd))
            rcalcrun = Popen(shlex.split(rccmd), stdin = cntrun.stdout, stdout = PIPE)

            with open(latlonghdr, 'w') as panohdr:
                rtcmd = 'rtrace -n {} -x 1500 -y 750 -fac "{}.oct"'.format(svp['viparams']['nproc'], os.path.join(svp['viparams']['newdir'], node['epwbase'][0]))
                logentry('Running rtrace: {}'.format(rtcmd))
                Popen(shlex.split(rtcmd), stdin = rcalcrun.stdout, stdout = panohdr)
                
    return skyentry

def mtx2vals(mtxlines, fwd, node, times):    
    for m, mtxline in enumerate(mtxlines):
        if 'NROWS' in mtxline:
            patches = int(mtxline.split('=')[1])
            
        elif mtxline == '\n':
            startline = m + 1
            break

    tothours = len(times)
    hours = [t.hour for t in times]
    mtxlarray = array([0.333 * sum([float(lv) for lv in fval.split(" ")]) for fval in mtxlines[startline:] if fval != '\n'], dtype=float)
    mtxshapearray = mtxlarray.reshape(patches, int(len(mtxlarray)/patches))
    vals = nsum(mtxshapearray, axis = 1)
    vvarray = transpose(mtxshapearray)
    vvlist = vvarray.tolist()
    vecvals = [[hours[x], (fwd+int(hours[x]/24))%7, *vvlist[x]] for x in range(tothours)]
    return(vecvals, vals)
    
def hdrsky(hdrfile, hdrmap, hdrangle, hdrradius):
    hdrangle = '1 {:.3f}'.format(hdrangle * math.pi/180) if hdrangle else '1 0'
    hdrfn = {'0': 'sphere2latlong', '1': 'sphere2angmap'}[hdrmap]
    return("# Sky material\nvoid colorpict hdr_env\n7 red green blue '{}' {}.cal sb_u sb_v\n0\n{}\n\nhdr_env glow env_glow\n0\n0\n4 1 1 1 0\n\nenv_glow bubble sky\n0\n0\n4 0 0 0 {}\n\n".format(hdrfile, hdrfn, hdrangle, hdrradius))

def retpmap(node, frame, scene):
    svp = scene.vi_params
    pportmats = ' '.join([mat.name.replace(" ", "_") for mat in bpy.data.materials if mat.vi_params.pport and mat.vi_params.get('radentry')])
    ammats = ' '.join([mat.name.replace(" ", "_") for mat in bpy.data.materials if mat.vi_params.mattype == '1' and mat.vi_params.radmatmenu == '7' and mat.vi_params.get('radentry')])
    pportentry = ' '.join(['-apo {}'.format(ppm) for ppm in pportmats.split()]) if pportmats else ''
    amentry = '-aps {}'.format(ammats) if ammats else ''
    cpentry = '-apc "{}-{}.cpm" {}'.format(svp['viparams']['filebase'], frame, node.pmapcno) if node.pmapcno else ''
    cpfileentry = '-ap "{}-{}.cpm" 50'.format(svp['viparams']['filebase'], frame) if node.pmapcno else ''  
    return amentry, pportentry, cpentry, cpfileentry   

def retsv(self, scene, frame, rtframe, chunk, rt):
    svcmd = "rcontrib -w -I -n {} {} -m sky_glow {}-{}.oct ".format(scene.vi_params['viparams']['nproc'], '-ab 1 -ad 8192 -aa 0 -ar 512 -as 1024 -lw 0.0002 ', scene.vi_params['viparams']['filebase'], frame)    
    rtrun = Popen(svcmd.split(), stdin = PIPE, stdout=PIPE, stderr=STDOUT, universal_newlines=True).communicate(input = '\n'.join([c[rt].decode('utf-8') for c in chunk]))                
    reslines = nsum(array([[float(rv) for rv in r.split('\t')[:3]] for r in rtrun[0].splitlines()[10:]]), axis = 1)
    reslines[reslines > 0] = 1
    return reslines.astype(int8)

def basiccalcapply(self, scene, frames, rtcmds, simnode, curres, pfile):  
    svp = scene.vi_params
    reslists = []
    ll = svp.vi_leg_levels
    increment = 1/ll
    bm = bmesh.new()
    bm.from_mesh(self.id_data.data)
    bm.transform(self.id_data.matrix_world)
    self['omax'], self['omin'], self['oave'], self['livires'] = {}, {}, {}, {}
    clearlayers(bm, 'f')
    geom = bm.verts if self['cpoint'] == '1' else bm.faces
    cindex = geom.layers.int['cindex']
    
    for f, frame in enumerate(frames):
        self['res{}'.format(frame)] = {}
        
        if svp['liparams']['unit'] == 'Lux':
            geom.layers.float.new('illu{}'.format(frame))
            geom.layers.float.new('virradm2{}'.format(frame))
            illures = geom.layers.float['illu{}'.format(frame)]
            virradm2res = geom.layers.float['virradm2{}'.format(frame)]
        elif svp['liparams']['unit'] == 'DF (%)':
            geom.layers.float.new('df{}'.format(frame))
            geom.layers.float.new('virradm2{}'.format(frame))
            dfres = geom.layers.float['df{}'.format(frame)]
            virradm2res = geom.layers.float['virradm2{}'.format(frame)]
        elif svp['liparams']['unit'] == 'W/m2 (f)':
            geom.layers.float.new('firrad{}'.format(frame))
            geom.layers.float.new('firradm2{}'.format(frame))
            firradres = geom.layers.float['firrad{}'.format(frame)]
            firradm2res = geom.layers.float['firradm2{}'.format(frame)]

        geom.layers.float.new('res{}'.format(frame))
        
        if geom.layers.string.get('rt{}'.format(frame)):
            rtframe = frame
        else:
            kints = [int(k[2:]) for k in geom.layers.string.keys()]
            rtframe = max(kints) if frame > max(kints) else min(kints)
        
        rt = geom.layers.string['rt{}'.format(rtframe)]
        logentry('Running rtrace: {}'.format(rtcmds[f]))

        for chunk in chunks([g for g in geom if g[rt]], int(svp['viparams']['nproc']) * 500):            
            rtrun = Popen(shlex.split(rtcmds[f]), stdin = PIPE, stdout=PIPE, stderr=PIPE, universal_newlines=True).communicate(input = '\n'.join([c[rt].decode('utf-8') for c in chunk]))   

            if rtrun[1]:
                logentry('rtrun error: {}'.format(rtrun[1]))
                pfile.check('CANCELLED')
                bm.free() 
                return 'CANCELLED'
            else:
                xyzirrad = array([[float(v) for v in sl.split('\t')[:3]] for sl in rtrun[0].splitlines()])

                if svp['liparams']['unit'] == 'W/m2 (f)':
                    firradm2 = nsum(xyzirrad * array([0.333, 0.333, 0.333]), axis = 1)   
                elif svp['liparams']['unit'] == 'Lux':
                    illu = nsum(xyzirrad * array([0.265, 0.67, 0.065]), axis = 1) * 179
                    virradm2 = nsum(xyzirrad * array([0.333, 0.333, 0.333]), axis = 1) 
                elif svp['liparams']['unit'] == 'DF (%)':
                    df = nsum(xyzirrad * array([0.265, 0.67, 0.065]), axis = 1) * 1.79
                    virradm2 = nsum(xyzirrad * array([0.333, 0.333, 0.333]), axis = 1)

                for gi, gp in enumerate(chunk):  
                    gparea = gp.calc_area() if svp['liparams']['cp'] == '0' else vertarea(bm, gp) 

                    if svp['liparams']['unit'] == 'W/m2 (f)':
                        gp[firradm2res] = firradm2[gi].astype(float32)
                        gp[firradres] = (firradm2[gi] * gparea).astype(float32)
                    elif svp['liparams']['unit'] == 'Lux':   
                        gp[illures] = illu[gi].astype(float32)  
                        gp[virradm2res] = virradm2[gi].astype(float32)
                    elif svp['liparams']['unit'] == 'DF (%)':
                        gp[dfres] = df[gi].astype(float32) 
                        gp[virradm2res] = virradm2[gi].astype(float32)

            curres += len(chunk)

            if pfile.check(curres) == 'CANCELLED':
                bm.free()
                return 'CANCELLED'

        if svp['liparams']['unit'] == 'Lux':
            oillu = array([g[illures] for g in geom]).astype(float64) 
            maxoillu, minoillu, aveoillu = nmax(oillu), nmin(oillu), nmean(oillu)
        elif svp['liparams']['unit'] == 'W/m2 (f)':
            oirrad = array([g[firradm2res] for g in geom]).astype(float64)
            maxoirrad, minoirrad, aveoirrad = nmax(oirrad), nmin(oirrad), nmean(oirrad)
        elif svp['liparams']['unit'] == 'DF (%)':
            odf = array([g[dfres] for g in geom]).astype(float64)
            maxodf, minodf, aveodf = nmax(odf), nmin(odf), nmean(odf)
               
        if svp['liparams']['unit'] == 'W/m2 (f)':
            oirradm2 = array([g[firradm2res] for g in geom]).astype(float64)
            oirrad = array([g[firradres] for g in geom]).astype(float64)
            maxoirrad, minoirrad, aveoirrad = nmax(oirrad), nmin(oirrad), nmean(oirrad)
            maxoirradm2, minoirradm2, aveoirradm2 = nmax(oirradm2), nmin(oirradm2), nmean(oirradm2)
            self['omax']['firrad{}'.format(frame)] = maxoirrad
            self['oave']['firrad{}'.format(frame)] = aveoirrad            
            self['omin']['firrad{}'.format(frame)] = minoirrad
            self['omax']['firradm2{}'.format(frame)] = maxoirradm2
            self['oave']['firradm2{}'.format(frame)] = aveoirradm2            
            self['omin']['firradm2{}'.format(frame)] = minoirradm2
            
        if svp['liparams']['unit'] == 'Lux':
            self['omax']['illu{}'.format(frame)] = maxoillu
            self['oave']['illu{}'.format(frame)] = aveoillu
            self['omin']['illu{}'.format(frame)] = minoillu
              
        elif svp['liparams']['unit'] == 'DF (%)':
            self['omax']['df{}'.format(frame)] = maxodf
            self['omin']['df{}'.format(frame)] = minodf
            self['oave']['df{}'.format(frame)] = aveodf

        posis = [v.co for v in bm.verts if v[cindex] > 0] if svp['liparams']['cp'] == '1' else [f.calc_center_median() for f in bm.faces if f[cindex] > 0]
        rgeom = [g for g in geom if g[cindex] > 0]
        rareas = [gp.calc_area() for gp in geom] if self['cpoint'] == '0' else [vertarea(bm, gp) for gp in geom]
        reslists.append([str(frame), 'Zone', self.id_data.name, 'X', ' '.join(['{:.3f}'.format(p[0]) for p in posis])])
        reslists.append([str(frame), 'Zone', self.id_data.name, 'Y', ' '.join(['{:.3f}'.format(p[1]) for p in posis])])
        reslists.append([str(frame), 'Zone', self.id_data.name, 'Z', ' '.join(['{:.3f}'.format(p[2]) for p in posis])])
        reslists.append([str(frame), 'Zone', self.id_data.name, 'Areas (m2)', ' '.join(['{:.3f}'.format(ra) for ra in rareas])])
        
        if svp['liparams']['unit'] == 'W/m2 (f)':
            firradbinvals = [self['omin']['firrad{}'.format(frame)] + (self['omax']['firrad{}'.format(frame)] - self['omin']['firrad{}'.format(frame)])/ll * (i + increment) for i in range(ll)]
            self['livires']['valbins'] = firradbinvals
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Full Irradiance (W/m2)', ' '.join(['{:.3f}'.format(g[firradres]) for g in rgeom])])

        elif svp['liparams']['unit'] == 'Lux':
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Illuminance (lux)', ' '.join(['{:.3f}'.format(g[illures]) for g in rgeom])])

        elif svp['liparams']['unit'] == 'DF (%)': 
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Illuminance (lux)', ' '.join(['{:.3f}'.format(g[dfres] * 100) for g in rgeom])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Visible Irradiance (W/m2)', ' '.join(['{:.3f}'.format(g[dfres]/1.79) for g in rgeom])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'DF (%)', ' '.join(['{:.3f}'.format(g[dfres]) for g in rgeom])])

    if len(frames) > 1:
        reslists.append(['All', 'Frames', '', 'Frames', ' '.join([str(f) for f in frames])])

        if svp['liparams']['unit'] == 'W/m2 (f)':
            reslists.append(['All', 'Zone', self.id_data.name, 'Average irradiance (W/m2)', ' '.join(['{:.3f}'.format(self['oave']['firradm2{}'.format(frame)]) for frame in frames])])
            reslists.append(['All', 'Zone', self.id_data.name, 'Maximum irradiance (W/m2)', ' '.join(['{:.3f}'.format(self['omax']['firradm2{}'.format(frame)]) for frame in frames])])
            reslists.append(['All', 'Zone', self.id_data.name, 'Minimum irradiance (W/m2)', ' '.join(['{:.3f}'.format(self['omin']['firradm2{}'.format(frame)]) for frame in frames])])
            reslists.append(['All', 'Zone', self.id_data.name, 'Average irradiance (W)', ' '.join(['{:.3f}'.format(self['oave']['firrad{}'.format(frame)]) for frame in frames])])
            reslists.append(['All', 'Zone', self.id_data.name, 'Maximum irradiance (W)', ' '.join(['{:.3f}'.format(self['omax']['firrad{}'.format(frame)]) for frame in frames])])
            reslists.append(['All', 'Zone', self.id_data.name, 'Minimum irradiance (W)', ' '.join(['{:.3f}'.format(self['omin']['firrad{}'.format(frame)]) for frame in frames])])

        elif svp['liparams']['unit'] in ('Lux', 'DF (%)'):            
            reslists.append(['All', 'Zone', self.id_data.name, 'Average illuminance (lux)', ' '.join(['{:.3f}'.format(self['oave']['illu{}'.format(frame)]) for frame in frames])])
            reslists.append(['All', 'Zone', self.id_data.name, 'Maximum illuminance (lux)', ' '.join(['{:.3f}'.format(self['omax']['illu{}'.format(frame)]) for frame in frames])])
            reslists.append(['All', 'Zone', self.id_data.name, 'Minimum illuminance (lux)', ' '.join(['{:.3f}'.format(self['omin']['illu{}'.format(frame)]) for frame in frames])])
            
            if svp['liparams']['unit'] == 'DF (%)': 
                reslists.append(['All', 'Zone', self.id_data.name, 'Average DF (lux)', ' '.join(['{:.3f}'.format(self['oave']['df{}'.format(frame)]) for frame in frames])])
                reslists.append(['All', 'Zone', self.id_data.name, 'Maximum DF (lux)', ' '.join(['{:.3f}'.format(self['omax']['df{}'.format(frame)]) for frame in frames])])
                reslists.append(['All', 'Zone', self.id_data.name, 'Minimum DF (lux)', ' '.join(['{:.3f}'.format(self['omin']['df{}'.format(frame)]) for frame in frames])])
                
            ir = []
            
            for frame in frames:
                if self['oave']['illu{}'.format(frame)] > 0:
                    ir.append('{:.3f}'.format(self['omin']['illu{}'.format(frame)]/self['oave']['illu{}'.format(frame)]))
                else:
                    ir.append('0')

            reslists.append(['All', 'Zone', self.id_data.name, 'Illuminance ratio', ' '.join(ir)])
 
    bm.transform(self.id_data.matrix_world.inverted())
    bm.to_mesh(self.id_data.data)
    bm.free()
    return reslists
    
def lhcalcapply(self, scene, frames, rtcmds, simnode, curres, pfile):
    reslists = []
    svp = scene.vi_params
    bm = bmesh.new()
    bm.from_mesh(self.id_data.data)
    self['omax'], self['omin'], self['oave'] = {}, {}, {}
    clearlayers(bm, 'f')
    geom = bm.verts if svp['liparams']['cp'] == '1' else bm.faces
    cindex = geom.layers.int['cindex']
    
    for f, frame in enumerate(frames): 
        geom.layers.float.new('res{}'.format(frame))

        if simnode['coptions']['unit'] == 'klxh':
            geom.layers.float.new('virradhm2{}'.format(frame))        
            geom.layers.float.new('virradh{}'.format(frame))
            geom.layers.float.new('illuh{}'.format(frame))
            virradm2res = geom.layers.float['virradhm2{}'.format(frame)]
            virradres = geom.layers.float['virradh{}'.format(frame)]
            illures = geom.layers.float['illuh{}'.format(frame)]
        elif simnode['coptions']['unit'] == 'kWh (f)':
            geom.layers.float.new('firradhm2{}'.format(frame))
            geom.layers.float.new('firradh{}'.format(frame))        
            firradm2res = geom.layers.float['firradhm2{}'.format(frame)]
            firradres = geom.layers.float['firradh{}'.format(frame)]
                 
        if geom.layers.string.get('rt{}'.format(frame)):
            rtframe = frame
        else:
            kints = [int(k[2:]) for k in geom.layers.string.keys()]
            rtframe  = max(kints) if frame > max(kints) else  min(kints)
        
        rt = geom.layers.string['rt{}'.format(rtframe)]
        gps = [g for g in geom if g[rt]]
        areas = array([g.calc_area() for g in gps] if svp['liparams']['cp'] == '0' else [vertarea(bm, g) for g in gps])

        for chunk in chunks(gps, int(svp['viparams']['nproc']) * 200):
            careas = array([c.calc_area() if svp['liparams']['cp'] == '0' else vertarea(bm, c) for c in chunk])
            rtrun = Popen(shlex.split(rtcmds[f]), stdin = PIPE, stdout=PIPE, stderr=PIPE, universal_newlines=True).communicate(input = '\n'.join([c[rt].decode('utf-8') for c in chunk]))  
            logentry('Running rtrace with command: {}'.format(rtcmds[f]))
            
            if rtrun[1]:
                logentry('Rtrace error: {}'.format(rtrun[1]))
                return 'CANCELLED'

            xyzirrad = array([[float(v) for v in sl.split('\t')[:3]] for sl in rtrun[0].splitlines()])

            if simnode['coptions']['unit'] == 'klxh':
                virradm2 = nsum(xyzirrad * array([0.333, 0.333, 0.333]), axis = 1) * 1e-3
                illu = nsum(xyzirrad * array([0.265, 0.67, 0.065]), axis = 1) * 0.179
                virrad = virradm2 * careas
                
            elif simnode['coptions']['unit'] == 'kWh (f)':
                firradm2 = nsum(xyzirrad * array([0.333, 0.333, 0.333]), axis = 1) * 1e-3
                firrad = firradm2 * careas
            
            for gi, gp in enumerate(chunk):
                if simnode['coptions']['unit'] == 'klxh':
                    gp[virradres] = virrad[gi].astype(float32)
                    gp[virradm2res] = virradm2[gi].astype(float32)
                    gp[illures] = illu[gi].astype(float32)
                elif simnode['coptions']['unit'] == 'kWh (f)':
                    gp[firradm2res] = firradm2[gi].astype(float32)
                    gp[firradres] = firrad[gi].astype(float32)
                           
            curres += len(chunk)
            
            if pfile.check(curres) == 'CANCELLED':
                bm.free()
                return {'CANCELLED'}
            
        if simnode['coptions']['unit'] == 'klxh':        
            oillu = array([g[illures] for g in gps])
            ovirrad = array([g[virradres] for g in gps])
            ovirradm2 = array([g[virradm2res] for g in gps])
            maxoillu = nmax(oillu)
            maxovirrad = nmax(ovirrad)
            maxovirradm2 = nmax(ovirradm2)
            minovirradm2 = nmin(ovirradm2)
            minovirrad = nmin(ovirrad)
            minoillu = nmin(oillu)
            aveovirradm2 = nmean(ovirradm2)
            aveovirrad = nmean(ovirrad)
            aveoillu = nmean(oillu)
            self['omax']['virradh{}'.format(frame)] = maxovirrad
            self['omin']['virradh{}'.format(frame)] = minovirrad
            self['oave']['virradh{}'.format(frame)] = aveovirrad
            self['omax']['virradhm2{}'.format(frame)] = maxovirradm2
            self['omin']['virradhm2{}'.format(frame)] = minovirradm2
            self['oave']['virradhm2{}'.format(frame)] = aveovirradm2
            self['omax']['illuh{}'.format(frame)] = maxoillu
            self['omin']['illuh{}'.format(frame)] = minoillu
            self['oave']['illuh{}'.format(frame)] = aveoillu
#            self['tablemlxh{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
#                 ['Luxhours (Mlxh)', '{:.1f}'.format(self['omin']['illuh{}'.format(frame)]), '{:.1f}'.format(self['oave']['illuh{}'.format(frame)]), '{:.1f}'.format(self['omax']['illuh{}'.format(frame)])]])
#            self['tablevim2{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
#                 ['Visual Irradiance (kWh/m2)', '{:.1f}'.format(self['omin']['virradhm2{}'.format(frame)]), '{:.1f}'.format(self['oave']['virradhm2{}'.format(frame)]), '{:.1f}'.format(self['omax']['virradhm2{}'.format(frame)])]])
#            self['tablevi{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
#                 ['Visual Irradiance (kWh)', '{:.1f}'.format(self['omin']['virradh{}'.format(frame)]), '{:.1f}'.format(self['oave']['virradh{}'.format(frame)]), '{:.1f}'.format(self['omax']['virradh{}'.format(frame)])]])

        elif simnode['coptions']['unit'] == 'kWh (f)':
            ofirradm2 = array([g[firradm2res] for g in gps])
            ofirrad = array([g[firradres] for g in gps])
            maxofirradm2 = nmax(ofirradm2)
            maxofirrad = nmax(ofirrad)
            minofirradm2 = nmin(ofirradm2)
            minofirrad = nmin(ofirrad)
            aveofirradm2 = nmean(ofirradm2)
            aveofirrad = nmean(ofirrad)
            self['omax']['firradh{}'.format(frame)] = maxofirrad
            self['omin']['firradh{}'.format(frame)] = minofirrad
            self['oave']['firradh{}'.format(frame)] = aveofirrad
            self['omax']['firradhm2{}'.format(frame)] = maxofirradm2
            self['omin']['firradhm2{}'.format(frame)] = minofirradm2
            self['oave']['firradhm2{}'.format(frame)] = aveofirradm2
#            self['tablefim2{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
#                 ['Full Irradiance (kWh/m2)', '{:.1f}'.format(self['omin']['firradhm2{}'.format(frame)]), '{:.1f}'.format(self['oave']['firradhm2{}'.format(frame)]), '{:.1f}'.format(self['omax']['firradhm2{}'.format(frame)])]])
#            self['tablefi{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
#                 ['Full Irradiance (kWh)', '{:.1f}'.format(self['omin']['firradh{}'.format(frame)]), '{:.1f}'.format(self['oave']['firradh{}'.format(frame)]), '{:.1f}'.format(self['omax']['firradh{}'.format(frame)])]])
            
        posis = [v.co for v in bm.verts if v[cindex] > 0] if self['cpoint'] == '1' else [f.calc_center_median() for f in bm.faces if f[cindex] > 1]
        reslists.append([str(frame), 'Zone', self.id_data.name, 'X', ' '.join([str(p[0]) for p in posis])])
        reslists.append([str(frame), 'Zone', self.id_data.name, 'Y', ' '.join([str(p[0]) for p in posis])])
        reslists.append([str(frame), 'Zone', self.id_data.name, 'Z', ' '.join([str(p[0]) for p in posis])])
        reslists.append([str(frame), 'Zone', self.id_data.name, 'Area', ' '.join([str(a) for a in areas])])
        
        if simnode['coptions']['unit'] == 'klxh':
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Visible irradiance (kwh)', ' '.join([str(g[virradres]) for g in geom if g[cindex] > 0])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Illuminance (klxh)', ' '.join([str(g[illures]) for g in geom if g[cindex] > 0])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Visible irradiance (kwh/m2)', ' '.join([str(g[virradm2res]) for g in geom if g[cindex] > 0])])
        elif simnode['coptions']['unit'] == 'kWh (f)':    
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Full irradiance (kwh)', ' '.join([str(g[firradres]) for g in geom if g[cindex] > 0])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Full irradiance (kwh/m2)', ' '.join([str(g[firradm2res]) for g in geom if g[cindex] > 0])])

    bm.to_mesh(self.id_data.data)
    bm.free()
    return reslists
    
def udidacalcapply(self, scene, frames, rccmds, simnode, curres, pfile):
    svp = scene.vi_params
    self['livires'] = {}
    self['compmat'] = [slot.material.name for slot in self.id_data.material_slots if slot.material.vi_params.mattype == '1'][0]
    patches = simnode['coptions']['cbdm_res']
    selobj(bpy.context.view_layer, self.id_data)
    bm = bmesh.new()
    bm.from_mesh(self.id_data.data)
    bm.transform(self.id_data.matrix_world)
    bm.normal_update()
    clearlayers(bm, 'f')
    geom = bm.verts if self['cpoint'] == '1' else bm.faces
    reslen = len(geom)
    self['omax'], self['omin'], self['oave'] = {}, {}, {}
    
    if self.get('wattres'):
        del self['wattres']
        
    illumod = array((47.4, 120, 11.6)).astype(float32)
    wattmod = array((0.265, 0.67, 0.065)).astype(float32)
    times = [datetime.datetime.strptime(time, "%d/%m/%y %H:%M:%S") for time in simnode['coptions']['times']]                  
    vecvals, vals = mtx2vals(open(simnode.inputs['Context in'].links[0].from_node['Options']['mtxfile'], 'r').readlines(), datetime.datetime(2015, 1, 1).weekday(), simnode, times)
    cbdm_days = list(set([t.timetuple().tm_yday for t in times]))
    cbdm_hours = [h for h in range(simnode['coptions']['cbdm_sh'], simnode['coptions']['cbdm_eh'])]
    dno, hno = len(cbdm_days), len(cbdm_hours)    
    (luxmin, luxmax) = (simnode['coptions']['dalux'], simnode['coptions']['asemax'])
    vecvals = array([vv[2:] for vv in vecvals if vv[1] < simnode['coptions']['weekdays']]).astype(float32)
    hours = vecvals.shape[0]
    restypes = ('da', 'sda', 'sv', 'ase', 'res', 'udilow', 'udisup', 'udiauto', 'udihi', 'firradh', 'firradhm2', 'maxlux', 'minlux', 'avelux')
    self['livires']['cbdm_days'] = cbdm_days
    self['livires']['cbdm_hours'] = cbdm_hours

    for f, frame in enumerate(frames):        
        reslists = [[str(frame), 'Time', '', 'Month', ' '.join([str(t.month) for t in times])]]
        reslists.append([str(frame), 'Time', '', 'Day', ' '.join([str(t.day) for t in times])])
        reslists.append([str(frame), 'Time', '', 'Hour', ' '.join([str(t.hour) for t in times])])
        reslists.append([str(frame), 'Time', '', 'DOS', ' '.join([str(t.timetuple().tm_yday - times[0].timetuple().tm_yday) for t in times])])

        for restype in restypes:
            geom.layers.float.new('{}{}'.format(restype, frame))
            
        (resda, ressda, ressv, resase, res, resudilow, resudisup, resudiauto, resudihi, firrad, firradm2, maxillu, minillu, aveillu) = [geom.layers.float['{}{}'.format(r, frame)] for r in restypes]
       
        if geom.layers.string.get('rt{}'.format(frame)):
            rtframe = frame
        else:
            kints = [int(k[2:]) for k in geom.layers.string.keys()]
            rtframe  = max(kints) if frame > max(kints) else  min(kints)
        
        rt = geom.layers.string['rt{}'.format(rtframe)]
        totarea = sum([g.calc_area() for g in geom if g[rt]]) if svp['liparams']['cp'] == '0' else sum([vertarea(bm, g) for g in geom if g[rt]])
                
        for ch, chunk in enumerate(chunks([g for g in geom if g[rt]], int(svp['viparams']['nproc']) * 40)):
            sensrun = Popen(shlex.split(rccmds[f]), stdin=PIPE, stdout=PIPE, stderr = PIPE, universal_newlines=True).communicate(input = '\n'.join([c[rt].decode('utf-8') for c in chunk]))
            resarray = array([[float(v) for v in sl.strip('\n').strip('\r\n').split('\t') if v] for sl in sensrun[0].splitlines()]).reshape(len(chunk), patches, 3).astype(float32)
            chareas = array([c.calc_area() for c in chunk]) if svp['liparams']['cp'] == '0' else array([vertarea(bm, c) for c in chunk]).astype(float32)
            sensarray = nsum(resarray*illumod, axis = 2).astype(float32)
            finalillu = inner(sensarray, vecvals).astype(float64)
            
            if svp['viparams']['visimcontext'] == 'LiVi CBDM' and simnode['coptions']['cbanalysis'] == '1':
                wattarray  = nsum(resarray*wattmod, axis = 2).astype(float32)
                firradm2array = inner(wattarray, vecvals).astype(float32)
                firradarray = (firradm2array.T * chareas).T.astype(float32)
                kwh = 0.001 * nsum(firradarray, axis = 1)
                kwhm2 = 0.001 * nsum(firradm2array, axis = 1)

                if not ch:
                    totfinalwatt = nsum(firradarray, axis = 0)
                    totfinalwattm2 = average(firradm2array, axis = 0) 
                    finalkwh = kwh
                    finalkwhm2 = kwhm2                    
                else:
                    totfinalwatt += nsum(firradarray, axis = 0)
                    totfinalwattm2 += average(firradm2array, axis = 0)
                    finalkwh = concatenate((finalkwh, kwh))
                    finalkwhm2 = concatenate((finalkwhm2, kwhm2))
                
                for gi, gp in enumerate(chunk):
                    gp[firrad] = kwh[gi]
                    gp[firradm2] = kwhm2[gi]
                    
            elif svp['viparams']['visimcontext'] == 'LiVi CBDM' and simnode['coptions']['cbanalysis'] == '2':   
                illuarray = nsum(resarray*illumod, axis = 2).astype(float32)                
                finalillu = inner(illuarray, vecvals).astype(float32)
                sdabool = choose(finalillu >= luxmin, [0, 1]).astype(int8)
                asebool = choose(finalillu >= luxmax, [0, 1]).astype(int8)                                  
                dabool = choose(finalillu >= simnode['coptions']['dalux'], [0, 1]).astype(int8)
                udilbool = choose(finalillu < simnode['coptions']['damin'], [0, 1]).astype(int8)
                udisbool = choose(finalillu < simnode['coptions']['dasupp'], [0, 1]).astype(int8) - udilbool
                udiabool = choose(finalillu < simnode['coptions']['daauto'], [0, 1]).astype(int8) - udilbool - udisbool
                udihbool = choose(finalillu >= simnode['coptions']['daauto'], [0, 1]).astype(int8)   
                sdabool = choose(finalillu >= luxmin, [0, 1]).astype(int8)
                asebool = choose(finalillu >= luxmax, [0, 1]).astype(int8)                                  
                daareares = (dabool.T*chareas).T             
                udilareares = (udilbool.T*chareas).T
                udisareares = (udisbool.T*chareas).T
                udiaareares = (udiabool.T*chareas).T
                udihareares = (udihbool.T*chareas).T
                aseareares = (asebool.T*chareas).T
                sdaareares = (sdabool.T*chareas).T 
                dares = dabool.sum(axis = 1)*100/hours
                udilow = udilbool.sum(axis = 1)*100/hours
                udisup = udisbool.sum(axis = 1)*100/hours
                udiauto = udiabool.sum(axis = 1)*100/hours
                udihi = udihbool.sum(axis = 1)*100/hours
                sdares = sdabool.sum(axis = 1)*100/hours
                aseres = asebool.sum(axis = 1)*1.0 
                
                if not ch:
                    totfinalillu = finalillu
                    totdaarea = nsum(100 * daareares/totarea, axis = 0)
                    totudiaarea = nsum(100 * udiaareares/totarea, axis = 0)
                    totudisarea = nsum(100 * udisareares/totarea, axis = 0)
                    totudilarea = nsum(100 * udilareares/totarea, axis = 0)
                    totudiharea = nsum(100 * udihareares/totarea, axis = 0)                
                    totsdaarea = nsum(sdaareares, axis = 0)
                    totasearea = nsum(aseareares, axis = 0)
                else:
                    nappend(totfinalillu, finalillu)
                    totdaarea += nsum(100 * daareares/totarea, axis = 0)
                    totudiaarea += nsum(100 * udiaareares/totarea, axis = 0)
                    totudilarea += nsum(100 * udilareares/totarea, axis = 0)
                    totudisarea += nsum(100 * udisareares/totarea, axis = 0)
                    totudiharea += nsum(100 * udihareares/totarea, axis = 0)
                    totsdaarea += nsum(sdaareares, axis = 0)
                    totasearea += nsum(aseareares, axis = 0)
                
                for gi, gp in enumerate(chunk):
                    gp[resda] = dares[gi]                
                    gp[res] = dares[gi]
                    gp[resudilow] = udilow[gi]
                    gp[resudisup] = udisup[gi]
                    gp[resudiauto] = udiauto[gi]
                    gp[resudihi] = udihi[gi]
                    gp[maxillu] = max(finalillu[gi])
                    gp[minillu] = min(finalillu[gi])
                    gp[aveillu] = nmean(finalillu[gi])
                    gp[ressda] = sdares[gi]
                    gp[resase] = aseres[gi]
                         
            curres += len(chunk)
            if pfile.check(curres) == 'CANCELLED':
                bm.free()
                return {'CANCELLED'}

        if svp['viparams']['visimcontext'] == 'LiVi CBDM' and simnode['coptions']['cbanalysis'] == '1':
            self['omax']['firradh{}'.format(frame)] = nmax(finalkwh).astype(float64)
            self['omin']['firradh{}'.format(frame)] = nmin(finalkwh).astype(float64)
            self['oave']['firradh{}'.format(frame)] = nmean(finalkwh).astype(float64)
            self['omax']['firradhm2{}'.format(frame)] = nmax(finalkwhm2).astype(float64)
            self['omin']['firradhm2{}'.format(frame)] = nmin(finalkwhm2).astype(float64)
            self['oave']['firradhm2{}'.format(frame)] = nmean(finalkwhm2).astype(float64)
            self['livires']['firradh{}'.format(frame)] =  (0.001*totfinalwatt).reshape(dno, hno).transpose().tolist()
            self['livires']['firradhm2{}'.format(frame)] =  (0.001*totfinalwattm2).reshape(dno, hno).transpose().tolist()            
            reslists.append([str(frame), 'Zone', self.id_data.name, 'kW', ' '.join([str(p) for p in 0.001 * totfinalwatt])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'kW/m2', ' '.join([str(p) for p in 0.001 * totfinalwattm2])])
            
        elif svp['viparams']['visimcontext'] == 'LiVi CBDM' and simnode['coptions']['cbanalysis'] == '2':
            dares = [gp[resda] for gp in geom] 
            udilow = [gp[resudilow] for gp in geom] 
            udisup = [gp[resudisup] for gp in geom]
            udiauto = [gp[resudiauto] for gp in geom]
            udihi = [gp[resudihi] for gp in geom]
            sdares = [gp[ressda] for gp in geom]
            aseres = [gp[resase] for gp in geom]
            self['omax']['udilow{}'.format(frame)] = max(udilow)
            self['omin']['udilow{}'.format(frame)] = min(udilow)
            self['oave']['udilow{}'.format(frame)] = nmean(udilow)
            self['omax']['udisup{}'.format(frame)] = max(udisup)
            self['omin']['udisup{}'.format(frame)] = min(udisup)
            self['oave']['udisup{}'.format(frame)] = nmean(udisup)
            self['omax']['udiauto{}'.format(frame)] = max(udiauto)
            self['omin']['udiauto{}'.format(frame)] = min(udiauto)
            self['oave']['udiauto{}'.format(frame)] = sum(udiauto)
            self['omax']['udihi{}'.format(frame)] = max(udihi)
            self['omin']['udihi{}'.format(frame)] = min(udihi)
            self['oave']['udihi{}'.format(frame)] = nmean(udihi)
            self['omax']['da{}'.format(frame)] = max(dares)
            self['omin']['da{}'.format(frame)] = min(dares)
            self['oave']['da{}'.format(frame)] = nmean(dares)
            self['omax']['maxlux{}'.format(frame)] = max(nmax(totfinalillu, axis = 1).astype(float64))
            self['omin']['maxlux{}'.format(frame)] = min(nmax(totfinalillu, axis = 1).astype(float64))
            self['oave']['maxlux{}'.format(frame)] = nmean(nmax(totfinalillu, axis = 1).astype(float64))
            self['omax']['minlux{}'.format(frame)] = max(nmin(totfinalillu, axis = 1).astype(float64))
            self['omin']['minlux{}'.format(frame)] = min(nmin(totfinalillu, axis = 1).astype(float64))
            self['oave']['minlux{}'.format(frame)] = nmean(nmin(totfinalillu, axis = 1).astype(float64))
            self['omax']['avelux{}'.format(frame)] = max(nmean(totfinalillu, axis = 1).astype(float64))
            self['omin']['avelux{}'.format(frame)] = min(nmean(totfinalillu, axis = 1).astype(float64))
            self['oave']['avelux{}'.format(frame)] = nmean(nmean(totfinalillu, axis = 1).astype(float64))
            self['livires']['dhilluave{}'.format(frame)] = average(totfinalillu, axis = 0).flatten().reshape(dno, hno).transpose().tolist()
            self['livires']['dhillumin{}'.format(frame)] = amin(totfinalillu, axis = 0).reshape(dno, hno).transpose().tolist()
            self['livires']['dhillumax{}'.format(frame)] = amax(totfinalillu, axis = 0).reshape(dno, hno).transpose().tolist()
            self['livires']['daarea{}'.format(frame)] = totdaarea.reshape(dno, hno).transpose().tolist()
            self['livires']['udiaarea{}'.format(frame)] = totudiaarea.reshape(dno, hno).transpose().tolist()
            self['livires']['udisarea{}'.format(frame)] = totudisarea.reshape(dno, hno).transpose().tolist()
            self['livires']['udilarea{}'.format(frame)] = totudilarea.reshape(dno, hno).transpose().tolist()
            self['livires']['udiharea{}'.format(frame)] = totudiharea.reshape(dno, hno).transpose().tolist()
            
            self['tableudil{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['UDI-l (% area)', '{:.1f}'.format(self['omin']['udilow{}'.format(frame)]), '{:.1f}'.format(self['oave']['udilow{}'.format(frame)]), '{:.1f}'.format(self['omax']['udilow{}'.format(frame)])]])
            self['tableudis{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['UDI-s (% area)', '{:.1f}'.format(self['omin']['udisup{}'.format(frame)]), '{:.1f}'.format(self['oave']['udisup{}'.format(frame)]), '{:.1f}'.format(self['omax']['udisup{}'.format(frame)])]])
            self['tableudia{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['UDI-a (% area)', '{:.1f}'.format(self['omin']['udiauto{}'.format(frame)]), '{:.1f}'.format(self['oave']['udiauto{}'.format(frame)]), '{:.1f}'.format(self['omax']['udiauto{}'.format(frame)])]])
            self['tableudie{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['UDI-e (% area)', '{:.1f}'.format(self['omin']['udihi{}'.format(frame)]), '{:.1f}'.format(self['oave']['udihi{}'.format(frame)]), '{:.1f}'.format(self['omax']['udihi{}'.format(frame)])]])
            self['tableillu{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['Illuminance (lux)', '{:.1f}'.format(self['omin']['minlux{}'.format(frame)]), '{:.1f}'.format(self['oave']['avelux{}'.format(frame)]), '{:.1f}'.format(self['omax']['maxlux{}'.format(frame)])]])
            self['tableda{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['Daylight availability (% time)', '{:.1f}'.format(self['omin']['da{}'.format(frame)]), '{:.1f}'.format(self['oave']['da{}'.format(frame)]), '{:.1f}'.format(self['omax']['da{}'.format(frame)])]])
            
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Daylight Autonomy Area (%)', ' '.join([str(p) for p in totdaarea])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'UDI-a Area (%)', ' '.join([str(p) for p in totudiaarea])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'UDI-s Area (%)', ' '.join([str(p) for p in totudisarea])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'UDI-l Area (%)', ' '.join([str(p) for p in totudilarea])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'UDI-h Area (%)', ' '.join([str(p) for p in totudiharea])])
        
            if svp['viparams']['visimcontext'] == 'LiVi Compliance' and simnode['coptions']['buildtype'] == '1':
                overallsdaarea = sum([g.calc_area() for g in geom if g[rt] and g[ressv]]) if self['cpoint'] == '0' else sum([vertarea(bm, g) for g in geom if g[rt] and g[ressv]]) 
            else:
                overallsdaarea = totarea

            self['omax']['sda{}'.format(frame)] = max(sdares)
            self['omin']['sda{}'.format(frame)] = min(sdares)
            self['oave']['sda{}'.format(frame)] = sum(sdares)/reslen
            self['omax']['ase{}'.format(frame)] = max(aseres)
            self['omin']['ase{}'.format(frame)] = min(aseres)
            self['oave']['ase{}'.format(frame)] = sum(aseres)/reslen
            self['livires']['asearea{}'.format(frame)] = (100 * totasearea/totarea).reshape(dno, hno).transpose().tolist()
            self['livires']['sdaarea{}'.format(frame)] = (100 * totsdaarea/overallsdaarea).reshape(dno, hno).transpose().tolist()
            self['tablesda{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['sDA (% hours)', '{:.1f}'.format(self['omin']['sda{}'.format(frame)]), '{:.1f}'.format(self['oave']['sda{}'.format(frame)]), '{:.1f}'.format(self['omax']['sda{}'.format(frame)])]])
            self['tablease{}'.format(frame)] = array([["", 'Minimum', 'Average', 'Maximum'], 
                ['ASE (hrs)', '{:.1f}'.format(self['omin']['ase{}'.format(frame)]), '{:.1f}'.format(self['oave']['ase{}'.format(frame)]), '{:.1f}'.format(self['omax']['ase{}'.format(frame)])]])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Annual Sunlight Exposure (% area)', ' '.join([str(p) for p in 100 * totasearea/totarea])])
            reslists.append([str(frame), 'Zone', self.id_data.name, 'Spatial Daylight Autonomy (% area)', ' '.join([str(p) for p in 100 * totsdaarea/overallsdaarea])])
        
    bm.transform(self.id_data.matrix_world.inverted())        
    bm.to_mesh(self.id_data.data)
    bm.free()
    return reslists


