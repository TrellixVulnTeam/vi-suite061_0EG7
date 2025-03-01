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

import bpy, os, itertools, subprocess, datetime, shutil, mathutils, bmesh
from .vi_func import selobj, facearea, selmesh, create_coll, selobs, logentry
from .envi_func import epentry, epschedwrite, get_con_node, boundpoly, get_zone_node, ret_areas
from .envi_mat import retuval

dtdf = datetime.date.fromordinal
caidict = {"0": "", "1": "Simple", "2": "Detailed", "3": "TrombeWall", "4": "AdaptiveConvectionAlgorithm"}
caodict = {"0": "", "1": "SimpleCombined", "2": "TARP", "3": "DOE-2", "4": "MoWiTT", "5": "AdaptiveConvectionAlgorithm"}

def enpolymatexport(exp_op, node, locnode, em, ec):
    scene = bpy.context.scene 
    svp = scene.vi_params
    svp['viparams']['hvactemplate'] = 0
    dp = bpy.context.evaluated_depsgraph_get()
    
    for frame in range(svp['enparams']['fs'], svp['enparams']['fe'] + 1):
        pvs = []
        gen = 0
        scene.frame_set(frame)
        geo_coll = bpy.data.collections['EnVi Geometry']
#        geo_coll.vi_params['enparams']['floorarea'] = {}

        geo_colls = geo_coll.children
#        onames = [o.name for coll in geo_colls for o in coll.objects if o.vi_params.envi_type == '0'] 
#        tcnames = [o.name for coll in geo_colls for o in coll.objects if o.vi_params.envi_type == '2']
        zonenames = [c.name for c in geo_colls]
        en_idf = open(os.path.join(svp['viparams']['newdir'], 'in{}.idf'.format(frame)), 'w')
        enng = [ng for ng in bpy.data.node_groups if ng.bl_label == 'EnVi Network'][0]
        enng['enviparams']['afn'] = 0
        badnodes = [node for node in enng.nodes if node.use_custom_color]

        for node in badnodes:
            node.hide = 0
            exp_op.report({'ERROR'}, 'Bad {} node in the EnVi network. Delete the node if not needed or make valid connections'.format(node.name))
            return

        if any([node.bl_idname in ('No_En_Net_SSFlow', 'No_En_Net_SFlow') for node in enng.nodes]):
            enng['enviparams']['afn'] = 1

        en_idf.write("!- Blender -> EnergyPlus\n!- Using the EnVi export scripts\n!- Author: Ryan Southall\n!- Date: {}\n\nVERSION,{};\n\n".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), svp['enparams']['epversion']))    
        params = ('Name', 'North Axis (deg)', 'Terrain', 'Loads Convergence Tolerance Value', 'Temperature Convergence Tolerance Value (deltaC)',
                  'Solar Distribution', 'Maximum Number of Warmup Days(from MLC TCM)')
        paramvs = ((node.loc, 'Default')[not node.loc], '0.00', ("City", "Urban", "Suburbs", "Country", "Ocean")[int(node.terrain)], '0.004', '0.4', 'FullInteriorAndExteriorWithReflections', '15')
        en_idf.write(epentry('Building', params, paramvs))
        params = ('Time Step in Hours', 'Algorithm', 'Algorithm', 'Default frequency of calculation', 'no zone sizing, system sizing, plant sizing, no design day, use weather file')
        paramvs = ('Timestep, {}'.format(node.timesteps), 'SurfaceConvectionAlgorithm:Inside, TARP', 'SurfaceConvectionAlgorithm:Outside, TARP',
                   'ShadowCalculation, {}, Periodic'.format(("PolygonClipping", "PixelCounting")[int(node.shadow_calc)]), 'SimulationControl, No,No,No,No,Yes')
    
        for ppair in zip(params, paramvs):
            en_idf.write(epentry('', [ppair[0]], [ppair[1]]) + ('', '\n\n')[ppair[0] == params[-1]])

        en_idf.write('HeatBalanceAlgorithm, ConductionTransferFunction;\n\n')
   
        params = ('Name', 'Begin Month', 'Begin Day of Month', 'Begin Year', 'End Month', 'End Day of Month', 'End Year', 'Day of Week for Start Day', 'Use Weather File Holidays and Special Days', 'Use Weather File Daylight Saving Period',\
        'Apply Weekend Holiday Rule', 'Use Weather File Rain Indicators', 'Use Weather File Snow Indicators')
        paramvs = ((node.loc, 'Default')[not node.loc], node.sdate.month, node.sdate.day, '', node.edate.month, node.edate.day, '', "", "Yes", "Yes", "No", "Yes", "Yes")
        en_idf.write(epentry('RunPeriod', params, paramvs))    

        en_idf.write("!-   ===========  ALL OBJECTS IN CLASS: MATERIAL & CONSTRUCTIONS ===========\n\n")

        for mat in bpy.data.materials:               
            mvp = mat.vi_params 

            if  mvp.envi_nodes and mvp.envi_nodes.nodes and mvp.envi_export == True:  
                for emnode in mvp.envi_nodes.nodes:
                    if emnode.bl_idname == 'No_En_Mat_Con' and emnode.active:
                        if emnode.envi_con_type == 'Window':                              
                            en_idf.write(emnode.ep_write(mat.name))                        
                        else:                            
                            if emnode.envi_con_type not in ('None', 'Shading', 'Aperture'):
                                en_idf.write(emnode.ep_write(mat.name))
                        if emnode.inputs['PV'].links:
                            gen = 1
                            pvs.append(emnode)    
        em.namedict = {}
        em.thickdict = {}
    
        en_idf.write("!-   ===========  ALL OBJECTS IN CLASS: ZONES ===========\n\n")
        zonenodes = [n for n in enng.nodes if hasattr(n, 'zone') and n.zone in zonenames]
        
        for coll in geo_colls:
            znode = get_zone_node(coll, enng)
            
            if znode:
                znode.update()                
                cvp = coll.vi_params                
                cvp['enparams']['floorarea'][str(frame)] = sum([ret_areas(o) for o in coll.objects if o.vi_params.envi_type == '0'])

                if coll.objects[0].vi_params.envi_type in ('0', '2'):
                    params = ('Name', 'Direction of Relative North (deg)', 'X Origin (m)', 'Y Origin (m)', 'Z Origin (m)', 'Type', 'Multiplier', 'Ceiling Height (m)', 'Volume (m3)',
                              'Floor Area (m2)', 'Zone Inside Convection Algorithm', 'Zone Outside Convection Algorithm', 'Part of Total Floor Area')
                    paramvs = (coll.name, 0, 0, 0, 0, 1, 1, 'autocalculate', '{:.1f}'.format(coll.objects[0]['volume']), 'autocalculate', caidict[znode.envi_ica], caodict[znode.envi_oca], 'Yes')
                    en_idf.write(epentry('Zone', params, paramvs))
        
        geo_coll.vi_params['enparams']['floorarea'][str(frame)] = sum([float(coll.vi_params['enparams']['floorarea'][str(frame)]) for coll in geo_colls])
        params = ('Starting Vertex Position', 'Vertex Entry Direction', 'Coordinate System')
        paramvs = ('UpperRightCorner', 'Counterclockwise', 'World')
        en_idf.write(epentry('GlobalGeometryRules', params, paramvs))
    
        en_idf.write("!-   ===========  ALL OBJECTS IN CLASS: SURFACE DEFINITIONS ===========\n\n")
        
        wfrparams = ['Name', 'Surface Type', 'Construction Name', 'Zone Name', 'Outside Boundary Condition', 'Outside Boundary Condition Object', 'Sun Exposure', 'Wind Exposure', 'View Factor to Ground', 'Number of Vertices']
        
        gens = []
        
        for coll in geo_colls:
            for obj in coll.objects:
                mats = [ms.material for ms in obj.material_slots]
                bm = bmesh.new()
                bm.from_object(obj, dp)
                bm.transform(obj.matrix_world)
                bm.normal_update()

                for face in [f for f in bm.faces if mats[f.material_index].vi_params.envi_nodes]:
                    mat = mats[face.material_index]
                    
                    for emnode in mat.vi_params.envi_nodes.nodes:
                        if emnode.bl_idname == 'No_En_Mat_Con' and emnode.active:
                            vcos = [v.co for v in face.verts]
                            (obc, obco, se, we) = boundpoly(obj, emnode, face, enng)
                            
                            if obc:
                                if emnode.envi_con_type in ('Wall', "Floor", "Roof"):
                                    if emnode.envi_con_makeup != "2":
                                        params = list(wfrparams) + ["X,Y,Z ==> Vertex {} (m)".format(v.index) for v in face.verts]                     
                                        paramvs = ['{}_{}'.format(obj.name, face.index), emnode.envi_con_type, mat.name, coll.name, obc, obco, se, we, 'autocalculate', len(face.verts)]+ ["  {0[0]:.4f}, {0[1]:.4f}, {0[2]:.4f}".format(vco) for vco in vcos]
                                        en_idf.write(epentry('BuildingSurface:Detailed', params, paramvs))
                                                                            
                                    if emnode.inputs['PV'].links:
                                        pvnode = emnode.inputs['PV'].links[0].from_node
                                        en_idf.write(pvnode.ep_write('{}_{}'.format(obj.name, face.index)))
                                        gens.append('{}_{}-pv'.format(obj.name, face.index))
                                        
                                elif emnode.envi_con_type in ('Door', 'Window')  and emnode.envi_con_makeup != "2":
                                    if len(face.verts) > 4:
                                        exp_op.report({'ERROR'}, 'Window/door in {} has more than 4 vertices'.format(obj.name))
                                        
                                    xav, yav, zav = mathutils.Vector(face.calc_center_median())
                                    params = list(wfrparams) + ["X,Y,Z ==> Vertex {} (m)".format(v.index) for v in face.verts]
                                    paramvs = ['{}_{}'.format(obj.name, face.index), 'Wall', '{}-frame'.format(mat.name), coll.name, obc, obco, se, we, 'autocalculate', len(face.verts)] + ["  {0[0]:.4f}, {0[1]:.4f}, {0[2]:.4f}".format(vco) for vco in vcos]
                                    en_idf.write(epentry('BuildingSurface:Detailed', params, paramvs))    
                                    obound = ('win-', 'door-')[emnode.envi_con_type == 'Door']+obco if obco else obco
                                    params = ['Name', 'Surface Type', 'Construction Name', 'Building Surface Name', 'Outside Boundary Condition Object', 'View Factor to Ground', 'Frame and Divider Name', 'Multiplier', 'Number of Vertices'] + \
                                    ["X,Y,Z ==> Vertex {} (m)".format(v.index) for v in face.verts]
                                    
                                    if emnode.fclass in ('0', '2'):
                                        paramvs = [('win-', 'door-')[emnode.envi_con_type == 'Door']+'{}_{}'.format(obj.name, face.index), emnode.envi_con_type, mat.name, '{}_{}'.format(obj.name, face.index), obound, 'autocalculate', '', '1', len(face.verts)] + \
                                        ["  {0[0]:.4f}, {0[1]:.4f}, {0[2]:.4f}".format((xav+(vco[0]-xav)*(1 - emnode.farea * 0.01), yav+(vco[1]-yav)*(1 - emnode.farea * 0.01), zav+(vco[2]-zav)*(1 - emnode.farea * 0.01))) for vco in vcos]
                                    else:
                                        paramvs = [('win-', 'door-')[mat.envi_con_type == 'Door']+'{}_{}'.format(obj.name, face.index), emnode.envi_con_type, mat.name, '{}_{}'.format(obj.name, face.index), obound, 'autocalculate', '{}-fad'.format(mat.name), '1', len(face.verts)] + \
                                        ["  {0[0]:.4f}, {0[1]:.4f}, {0[2]:.4f}".format((vco[0] + (1, -1)[vco[0] - xav > 0]*(0.001+emnode.fw, 0)[abs(vco[0] - xav) < 0.0001], vco[1] + (1, -1)[vco[1] - yav > 0]*(0.001+emnode.fw, 0)[abs(vco[1] - yav) < 0.0001], vco[2] + (1, -1)[vco[2] - zav > 0]*(0.001+emnode.fw, 0)[abs(vco[2] - zav) < 0.0001])) for vco in vcos]
                                    
                                    en_idf.write(epentry('FenestrationSurface:Detailed', params, paramvs))
                    
                                elif emnode.envi_con_type == 'Shading' and obj.vi_params.envi_type != '1':
                                    params = ['Name', 'Transmittance Schedule Name', 'Number of Vertices'] + ['X,Y,Z ==> Vertex {} (m)'.format(v.index) for v in face.verts]
                                    paramvs = ['{}_{}'.format(obj.name, face.index), '', len(face.verts)] + ['{0[0]:.4f}, {0[1]:.4f}, {0[2]:.4f}'.format(vco) for vco in vcos]
                                    en_idf.write(epentry('Shading:{}:Detailed'.format('Building'), params, paramvs))
                                    
                                    if emnode.inputs['PV'].links:
                                        pvnode = emnode.inputs['PV'].links[0].from_node
                                        en_idf.write(pvnode.ep_write('{}_{}'.format(obj.name, face.index), face.calc_area()))
                                        gens.append('{}_{}-pv'.format(obj.name, face.index))
                                        
                            if obj.vi_params.envi_type == '1':
                                params = ['Name', 'Transmittance Schedule Name', 'Number of Vertices'] + ['X,Y,Z ==> Vertex {} (m)'.format(v.index) for v in face.verts]
                                paramvs = ['{}_{}'.format(obj.name, face.index), '', len(face.verts)] + ['{0[0]:.4f}, {0[1]:.4f}, {0[2]:.4f}'.format(vco) for vco in vcos]
                                en_idf.write(epentry('Shading:{}:Detailed'.format('Site'), params, paramvs))
                                
                                if emnode.inputs['PV'].links:
                                    pvnode = emnode.inputs['PV'].links[0].from_node
                                    en_idf.write(pvnode.ep_write('{}_{}'.format(obj.name, face.index), face.calc_area()))
                                    gens.append('{}_{}-pv'.format(obj.name, face.index))
                bm.free()
    
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: SCHEDULES ===========\n\n")
        params = ('Name', 'Lower Limit Value', 'Upper Limit Value', 'Numeric Type', 'Unit Type')
        paramvs = ("Temperature", -60, 200, "CONTINUOUS", "Temperature")
        en_idf.write(epentry('ScheduleTypeLimits', params, paramvs))
        params = ('Name', 'Lower Limit Value', 'Upper Limit Value', 'Numeric Type')
        paramvs = ("Control Type", 0, 4, "DISCRETE")
        en_idf.write(epentry('ScheduleTypeLimits', params, paramvs))
        params = ('Name', 'Lower Limit Value', 'Upper Limit Value', 'Numeric Type')
        paramvs = ("Fraction", 0, 1, "CONTINUOUS")
        en_idf.write(epentry('ScheduleTypeLimits', params, paramvs))
        params = ['Name']
        paramvs = ["Any Number"]
        en_idf.write(epentry('ScheduleTypeLimits', params, paramvs))
        en_idf.write(epschedwrite('Default outdoor CO2 levels 400 ppm', 'Any number', ['Through: 12/31'], [['For: Alldays']], [[[['Until: 24:00,{}'.format('400')]]]]))
    
        for zn in zonenodes:
            for schedtype in ('VASchedule', 'TSPSchedule', 'HVAC', 'Occupancy', 'Equipment', 'Infiltration'):
                if schedtype == 'HVAC' and zn.inputs[schedtype].links:
                    en_idf.write(zn.inputs[schedtype].links[0].from_node.eptcwrite(zn.zone))
                    try:
                        en_idf.write(zn.inputs[schedtype].links[0].from_node.inputs['Schedule'].links[0].from_node.epwrite(zn.zone+'_hvacsched', 'Fraction'))                            
                    except:
                        en_idf.write(epschedwrite(zn.zone + '_hvacsched', 'Fraction', ['Through: 12/31'], [['For: Alldays']], [[[['Until: 24:00, 1']]]]))
    
                    hsdict = {'HSchedule': '_htspsched', 'CSchedule': '_ctspsched'}
                    tvaldict = {'HSchedule': zn.inputs[schedtype].links[0].from_node.envi_htsp, 'CSchedule': zn.inputs[schedtype].links[0].from_node.envi_ctsp}
                    for sschedtype in hsdict: 
                        if zn.inputs[schedtype].links[0].from_node.inputs[sschedtype].links:
                            en_idf.write(zn.inputs[schedtype].links[0].from_node.inputs[sschedtype].links[0].from_node.epwrite(zn.zone+hsdict[sschedtype], 'Temperature'))                            
                        else:
                            en_idf.write(epschedwrite(zn.zone + hsdict[sschedtype], 'Temperature', ['Through: 12/31'], [['For: Alldays']], [[[['Until: 24:00,{}'.format(tvaldict[sschedtype])]]]]))
    
                elif schedtype == 'Occupancy' and zn.inputs[schedtype].links:
                    osdict = {'OSchedule': '_occsched', 'ASchedule': '_actsched', 'WSchedule': '_wesched', 'VSchedule': '_avsched', 'CSchedule': '_closched'}
                    ovaldict = {'OSchedule': 1, 'ASchedule': zn.inputs[schedtype].links[0].from_node.envi_occwatts, 
                                'WSchedule': zn.inputs[schedtype].links[0].from_node.envi_weff, 'VSchedule': zn.inputs[schedtype].links[0].from_node.envi_airv, 
                                'CSchedule': zn.inputs[schedtype].links[0].from_node.envi_cloth}
                    for sschedtype in osdict:
                        svariant = 'Fraction' if sschedtype == 'OSchedule' else 'Any Number'
                        if zn.inputs[schedtype].links[0].from_node.inputs[sschedtype].links:
                            en_idf.write(zn.inputs[schedtype].links[0].from_node.inputs[sschedtype].links[0].from_node.epwrite(zn.zone + osdict[sschedtype], svariant))
                        else:
                            en_idf.write(epschedwrite(zn.zone + osdict[sschedtype], svariant, ['Through: 12/31'], [['For: Alldays']], [[[['Until: 24:00,{:.3f}'.format(ovaldict[sschedtype])]]]]))
    
                elif schedtype == 'Equipment' and zn.inputs[schedtype].links:
                    if not zn.inputs[schedtype].links[0].from_node.inputs['Schedule'].links:
                        en_idf.write(epschedwrite(zn.zone + '_eqsched', 'Fraction', ['Through: 12/31'], [['For: Alldays']], [[[['Until: 24:00,1']]]]))
                    else:
                        en_idf.write(zn.inputs[schedtype].links[0].from_node.inputs['Schedule'].links[0].from_node.epwrite(zn.zone+'_eqsched', 'Fraction'))
                elif schedtype == 'Infiltration' and zn.inputs[schedtype].links:
                    if not zn.inputs[schedtype].links[0].from_node.inputs['Schedule'].links:
                        en_idf.write(epschedwrite(zn.zone + '_infsched', 'Fraction', ['Through: 12/31'], [['For: Alldays']], [[[['Until: 24:00,{}'.format(1)]]]]))
                    else:
                        en_idf.write(zn.inputs[schedtype].links[0].from_node.inputs['Schedule'].links[0].from_node.epwrite(zn.zone+'_infsched', 'Fraction'))
                elif schedtype == 'VASchedule' and zn.inputs[schedtype].links:
                    en_idf.write(zn.inputs[schedtype].links[0].from_node.epwrite(zn.zone+'_vasched', 'Fraction'))
    
                elif schedtype == 'TSPSchedule' and zn.inputs[schedtype].links:
                    en_idf.write(zn.inputs[schedtype].links[0].from_node.epwrite(zn.zone+'_tspsched', 'Temperature'))
                    
        ssafnodes = [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_SSFlow']

        for zn in ssafnodes:
            for schedtype in ('VASchedule', 'TSPSchedule'):
                if schedtype == 'VASchedule' and zn.inputs[schedtype].links:
                    en_idf.write(zn.inputs[schedtype].links[0].from_node.epwrite('{}_vasched'.format(zn.name), 'Fraction'))
    
                elif schedtype == 'TSPSchedule' and zn.inputs[schedtype].links:
                    en_idf.write(zn.inputs[schedtype].links[0].from_node.epwrite('{}_tspsched'.format(zn.name), 'Temperature'))
                
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: GENERATORS ===========\n\n")
        
        if gen:
            params = ('Name', 'Generator List Name', 'Generator Operation Scheme Type', 
                      'Generator Demand Limit Scheme Purchased Electric Demand Limit {W}',
                      'Generator Track Schedule Name Scheme Schedule Name',
                      'Generator Track Meter Scheme Meter Name', 'Electrical Buss Type',
                      'Inverter Name')
            paramvs = 'Electric Load Center', 'PVs', 'Baseload', '0', '', '', 'DirectCurrentWithInverter', 'Simple Ideal Inverter'
            en_idf.write(epentry("ElectricLoadCenter:Distribution", params, paramvs))
            
            params = ('Name', 'Availability Schedule Name', 'Zone Name', 'Radiative Fraction', 'Inverter Efficiency')
            paramvs = ('Simple Ideal Inverter', '', '', 0.0, 1.0)
            en_idf.write(epentry("ElectricLoadCenter:Inverter:Simple", params, paramvs))
            
            
            params = ["Name"] + [item for i, pv in enumerate(gens) for item in ['Generator {} Name'.format(i), 'Generator {} Object Type'.format(i), 
                     'Generator {} Rated Electric Power Output (W)'.format(i), 'Generator {} Availability Schedule Name'.format(i),
                     'Generator {} Rated Thermal to Electrical Power Ratio'.format(i)]] 

            paramvs = ['PVs'] + [item for pv in gens for item in [pv, 'Generator:Photovoltaic', '20000', '', '']] 
            en_idf.write(epentry("ElectricLoadCenter:Generators", params, paramvs))

        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: THERMOSTSTATS ===========\n\n")
        for zn in zonenodes:
            for hvaclink in zn.inputs['HVAC'].links:
                en_idf.write(hvaclink.from_node.eptspwrite(zn.zone))
    
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: EQUIPMENT ===========\n\n")
        for zn in zonenodes:
            for hvaclink in zn.inputs['HVAC'].links:
                hvaczone = hvaclink.from_node
                if not hvaczone.envi_hvact:
                    en_idf.write(zn.inputs['HVAC'].links[0].from_node.epewrite(zn.zone))
        
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: HVAC ===========\n\n")
        for zn in zonenodes:
            for hvaclink in zn.inputs['HVAC'].links:
                hvacnode = hvaclink.from_node
                if hvacnode.envi_hvact:
                    en_idf.write(hvacnode.hvactwrite(zn.zone))
                else:
                    en_idf.write(hvacnode.ephwrite(zn.zone))
    
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: OCCUPANCY ===========\n\n")
        for zn in zonenodes:
            for occlink in zn.inputs['Occupancy'].links:
                en_idf.write(occlink.from_node.epwrite(zn.zone))

        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: OTHER EQUIPMENT ===========\n\n")
        for zn in zonenodes:
            for eqlink in zn.inputs['Equipment'].links:
                en_idf.write(eqlink.from_node.oewrite(zn.zone))
       
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: CONTAMINANTS ===========\n\n")
        zacb = 0
        for zn in zonenodes:
            if not zacb:
                for occlink in zn.inputs['Occupancy'].links:
                    if occlink.from_node.envi_co2 and occlink.from_node.envi_comfort:
                        params = ('Carbon Dioxide Concentration', 'Outdoor Carbon Dioxide Schedule Name', 'Generic Contaminant Concentration', 'Outdoor Generic Contaminant Schedule Name')
                        paramvs = ('Yes', 'Default outdoor CO2 levels 400 ppm', 'No', '')
                        en_idf.write(epentry('ZoneAirContaminantBalance', params, paramvs))
                        zacb = 1
                        break
    
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: INFILTRATION ===========\n\n")
        for zn in zonenodes:
            for inflink in zn.inputs['Infiltration'].links:
                en_idf.write(inflink.from_node.epwrite(zn.zone))
                    
        en_idf.write("\n!-   ===========  ALL OBJECTS IN CLASS: AIRFLOW NETWORK ===========\n\n")
        
        if enng and enng['enviparams']['afn']:
            writeafn(exp_op, en_idf, enng)
    
        en_idf.write("!-   ===========  ALL OBJECTS IN CLASS: EMS ===========\n\n")   
        emsprognodes = [pn for pn in enng.nodes if pn.bl_idname == 'No_En_Net_Prog' and not pn.use_custom_color and pn.text_file]
        
        for prognode in emsprognodes:
            en_idf.write(prognode.epwrite())
        
        emspynodes = [pn for pn in enng.nodes if pn.bl_idname == 'No_En_Net_EMSPy' and not pn.use_custom_color and pn.py_mod and pn.py_class]
        
        for pynode in emspynodes:
            en_idf.write(pynode.epwrite())

        en_idf.write("!-   ===========  ALL OBJECTS IN CLASS: REPORT VARIABLE ===========\n\n")
        epentrydict = {"Output:Variable,*,Zone Air Temperature,hourly;\n": node.restt, "Output:Variable,*,Zone Other Equipment Total Heating Rate,hourly;\n": node.resoeg,
                       "Output:Variable,*,Zone Air System Sensible Heating Rate,hourly;\n": node.restwh, "Output:Variable,*,Zone Air System Sensible Cooling Rate,hourly;\n": node.restwc,
                       "Output:Variable,*,Zone Ideal Loads Supply Air Sensible Heating Rate, hourly;\n": node.ressah, "Output:Variable,*,Zone Ideal Loads Heat Recovery Sensible Heating Rate, hourly;\n": node.reshrhw, 
                       "Output:Variable,*,Zone Ideal Loads Supply Air Sensible Cooling Rate,hourly;\n": node.ressac,
                       "Output:Variable,*,Zone Thermal Comfort Fanger Model PMV,hourly;\n": node.rescpm, "Output:Variable,*,Zone Thermal Comfort Fanger Model PPD,hourly;\n": node.rescpp, "Output:Variable,*,AFN Zone Infiltration Volume, hourly;\n": node.resim and enng['enviparams']['afn'],
                       "Output:Variable,*,AFN Zone Infiltration Air Change Rate, hourly;\n": node.resiach and enng['enviparams']['afn'], "Output:Variable,*,Zone Infiltration Current Density Volume,hourly;\n": node.resim and not enng['enviparams']['afn'],
                       "Output:Variable,*,Zone Infiltration Air Change Rate, hourly;\n": node.resiach and not enng['enviparams']['afn'], "Output:Variable,*,Zone Windows Total Transmitted Solar Radiation Rate,hourly;\n": node.reswsg,
                       "Output:Variable,*,AFN Node CO2 Concentration,hourly;\n": node.resco2 and enng['enviparams']['afn'], "Output:Variable,*,Zone Air CO2 Concentration,hourly;\n": node.resco2 and not enng['enviparams']['afn'],
                       "Output:Variable,*,Zone Mean Radiant Temperature,hourly;\n": node.resmrt, "Output:Variable,*,Zone People Occupant Count,hourly;\n": node.resocc,
                       "Output:Variable,*,Zone Air Relative Humidity,hourly;\n": node.resh, "Output:Variable,*,Zone Air Heat Balance Surface Convection Rate, hourly;\n": node.resfhb,
                       "Output:Variable,*,Generator Produced DC Electric Energy,hourly;\n": node.respve, "Output:Variable,*,Generator Produced DC Electric Power,hourly;\n": node.respvw,
                       "Output:Variable,*,Generator PV Array Efficiency,hourly;\n": node.respveff, "Output:Variable,*,Generator PV Cell Temperature,hourly;\n": node.respvt}
        
        for amb in ("Output:Variable,*,Site Outdoor Air Drybulb Temperature,Hourly;\n", "Output:Variable,*,Site Wind Speed,Hourly;\n", "Output:Variable,*,Site Wind Direction,Hourly;\n",
                    "Output:Variable,*,Site Outdoor Air Relative Humidity,hourly;\n", "Output:Variable,*,Site Direct Solar Radiation Rate per Area,hourly;\n", "Output:Variable,*,Site Diffuse Solar Radiation Rate per Area,hourly;\n"):
            en_idf.write(amb)            
        
        for ep in epentrydict:
            if epentrydict[ep]:
                en_idf.write(ep)
        
        if enng['enviparams']['afn']:
            if node.resl12ms:
                for cnode in [cnode for cnode in enng.nodes if cnode.bl_idname == 'No_En_Net_SFlow']:
                    for sno in cnode['sname']:
                        en_idf.write("Output:Variable,{0},AFN Linkage Node 1 to Node 2 Volume Flow Rate,hourly;\nOutput:Variable,{0},AFN Linkage Node 2 to Node 1 Volume Flow Rate,hourly;\n".format(sno))
                        en_idf.write("Output:Variable,{0},AFN Linkage Node 1 to Node 2 Pressure Difference,hourly;\n".format(sno))
                for snode in [snode for snode in enng.nodes if snode.bl_idname == 'No_En_Net_SSFlow']:
                    for sno in snode['sname']:
                        en_idf.write("Output:Variable,{0},AFN Linkage Node 1 to Node 2 Volume Flow Rate,hourly;\nOutput:Variable,{0},AFN Linkage Node 2 to Node 1 Volume Flow Rate,hourly;\n".format(sno))
                        en_idf.write("Output:Variable,{0},AFN Linkage Node 1 to Node 2 Pressure Difference,hourly;\n".format(sno))
            if node.reslof == True:
                for snode in [snode for snode in enng.nodes if snode.bl_idname == 'No_En_Net_SSFlow']:
                    if snode.linkmenu in ('SO', 'DO', 'HO'):
                        for sno in snode['sname']:
                            en_idf.write("Output:Variable,{},AFN Surface Venting Window or Door Opening Factor,hourly;\n".format(sno))
    
        en_idf.write("Output:Table:SummaryReports,\
        AllSummary;              !- Report 1 Name")
        en_idf.close()
        
        if svp['enparams'].get('hvactemplate'):
            os.chdir(svp['viparams']['newdir'])
            ehtempcmd = "ExpandObjects {}".format(os.path.join(svp['viparams']['newdir'], 'in.idf'))
            subprocess.call(ehtempcmd.split())
            shutil.copyfile(os.path.join(svp['viparams']['newdir'], 'expanded.idf'), os.path.join(svp['viparams']['newdir'], 'in.idf')) 
        
        if 'in{}.idf'.format(frame) not in [im.name for im in bpy.data.texts]:
            bpy.data.texts.load(os.path.join(svp['viparams']['newdir'], 'in{}.idf'.format(frame)))
        else:
            bpy.data.texts['in{}.idf'.format(frame)].filepath = os.path.join(svp['viparams']['newdir'], 'in{}.idf'.format(frame))

def pregeo(context, op):
    scene = context.scene
    svp = scene.vi_params
    depsgraph = bpy.context.evaluated_depsgraph_get()

    if context.active_object and context.active_object.mode == 'EDIT':
        bpy.ops.object.editmode_toggle()

    eg = create_coll(context, 'EnVi Geometry')
    eg.vi_params['enparams'] = {}
    eg.vi_params['enparams']['floorarea'] = {}

    for chil in eg.children:
        [bpy.data.objects.remove(o, do_unlink = True, do_id_user=True, do_ui_user=True) for o in chil.objects]
        eg.children.unlink(chil)
        bpy.data.collections.remove(chil)

    for mesh in bpy.data.meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
            
    for material in bpy.data.materials:
        material.vi_params.envi_export = 0
        material.vi_params['enparams'] = {'area': 0}
        
        if material.users == 0:
            bpy.data.materials.remove(material)
         
    for c in [c for c in bpy.data.collections if c.name != 'EnVi Geometry' and c.name not in [c.name for c in eg.children]]:
        c.vi_params.envi_zone = 1 if any([o.vi_params.vi_type == '1' for o in c.objects]) else 0
        c_name = c.name.upper().replace('-', '_').replace('/', '_')
        cobs = [o for o in c.objects if o.visible_get() and o.type == 'MESH']

        if c.vi_params.envi_zone:
            eg.children.link(bpy.data.collections.new('EN_{}'.format(c_name)))
            
            for o in cobs:
                if [f for f in o.data.polygons if o.material_slots and \
                    o.material_slots[f.material_index].material and \
                    o.material_slots[f.material_index].material.vi_params.envi_nodes and \
                    get_con_node(o.material_slots[f.material_index].material.vi_params).envi_con_type != 'None']:
                    selobj(context.view_layer, o)
                    obm = bmesh.new()
                    obm.from_mesh(o.evaluated_get(depsgraph).to_mesh())
                    o.to_mesh_clear()
                    
                    if not obm.faces.layers.int.get('viuid'):
                        obm.faces.layers.int.new('viuid')

                    uid = obm.faces.layers.int['viuid']
                    # obm.faces.layers.string.new('viuid')
                    # fo = obm.faces.layers.string['viuid']
                    exp_faces = [f for f in obm.faces if o.material_slots[f.material_index].material.vi_params.envi_nodes]

                    for face in obm.faces:
                        uids = [f[uid] for f in exp_faces]
                        face[uid] = face[uid] if face[uid] else max(uids) + 1
#                       face[fo] = '{}#{}'.format(o.name.encode(), face[uid])

                    obm.to_mesh(o.data)
                    obm.free()    
                    bpy.ops.object.duplicate(linked=False)
                    no = context.active_object.copy()  
                    no.location += context.node.geo_offset                       
                    bpy.ops.object.delete()
                    no.name = 'en_{}'.format(c_name) 
                    bpy.data.collections['EN_{}'.format(c_name)].objects.link(no)
            
    for chil in eg.children: 
        if chil.objects:
            therm = 0
            for o in chil.objects:
                bm = bmesh.new()
                bm.from_mesh(o.evaluated_get(depsgraph).to_mesh())
                o.to_mesh_clear()
                bmesh.ops.remove_doubles(bm, verts = bm.verts, dist = 0.005) 
                bmesh.ops.split_edges(bm, edges = bm.edges)
                bmesh.ops.dissolve_degenerate(bm, dist = 0.005, edges = bm.edges)
                bmesh.ops.dissolve_limit(bm, angle_limit = 0.001, use_dissolve_boundaries = False, verts = bm.verts, delimit = {'MATERIAL'})
                bmesh.ops.delete(bm, geom = [e for e in bm.edges if not e.link_faces] + [v for v in bm.verts if not v.link_faces], context = 'VERTS')
                bmesh.ops.delete(bm, geom = [f for f in bm.faces if f.calc_area() < 0.001], context = 'FACES') 
                bmesh.ops.delete(bm, geom = [f for f in bm.faces if o.material_slots[f.material_index].material == None], context = 'FACES') 
                bmesh.ops.delete(bm, geom = [f for f in bm.faces if not o.material_slots[f.material_index].material.vi_params.envi_nodes], context = 'FACES')
                bmesh.ops.delete(bm, geom = [f for f in bm.faces if get_con_node(o.material_slots[f.material_index].material.vi_params).envi_con_type == 'None'], context = 'FACES')

                # if not bm.faces.layers.int.get('viuid'):
                #     bm.faces.layers.int.new('viuid')

                # uid = bm.faces.layers.int['viuid']

                if not len(bm.faces):
                    bpy.data.objects.remove(o, do_unlink = True, do_id_user=True, do_ui_user=True)
                else:
                    if o.vi_params.envi_type != '1':
                        # bm.faces.layers.string.new('oname')
                        # fo = bm.faces.layers.string['oname']
                        # exp_faces = [f for f in bm.faces if o.material_slots[f.material_index].material.vi_params.envi_nodes]
    
                        # for face in bm.faces:
                        #     uids = [f[uid] for f in exp_faces]
                        #     face[fo] = o.name.encode()
                        #     face[uid] = face[uid] if face[uid] else max(uids) + 1

                        if o.vi_params.envi_type == '0':
                            therm = 1

                    bm.to_mesh(o.data)
                bm.free()
                   
            selobs(context.view_layer, [o.name for o in chil.objects])
            bpy.ops.object.join()
            new_ob = bpy.context.active_object
            new_ob.name = '{}'.format(chil.name)

            if therm:
                new_ob.vi_params.envi_type = '0' 
                
            bm = bmesh.new()
            bm.from_mesh(new_ob.evaluated_get(depsgraph).to_mesh())
            
#            bmesh.ops.triangulate(bm, faces=bm.faces)
            bm.transform(new_ob.matrix_world)
            print(bm.calc_volume())
#            bmesh.ops.connect_verts_nonplanar(bm, angle_limit=0.0175, faces=bm.faces)
#            print(bm.calc_volume())
            bmesh.ops.triangulate(bm, faces=bm.faces)
            print(bm.calc_volume())
            new_ob['auto_volume'] = bm.calc_volume()
            bm.free()
        
            if new_ob.vi_params.envi_type == '1':
                if not new_ob.material_slots:
                    if 'en_shading' not in [m.name for m in bpy.data.materials]:
                        bpy.data.materials.new('en_shading')
                        bpy.ops.object.material_slot_add()
                        bpy.ops.material.new()
                        new_ob.material_slots[0].material = bpy.data.materials['en_shading']
                        new_ob.material_slots[0].material.diffuse_color = (1, 0, 0, 1)
            
    if not [ng for ng in bpy.data.node_groups if ng.bl_label == 'EnVi Network']:
        bpy.ops.node.new_node_tree(type='EnViN', name ="EnVi Network") 

        for screen in bpy.data.screens:
            for area in [area for area in screen.areas if area.type == 'NODE_EDITOR' and area.spaces[0].tree_type == 'ViN']:
                area.spaces[0].node_tree = context.node.id_data
    
    enng = [ng for ng in bpy.data.node_groups if ng.bl_label == 'EnVi Network'][0]
    enng.use_fake_user = True
    enng['enviparams'] = {'wpca': 0, 'wpcn': 0, 'crref': 0, 'afn': 0, 'pcm':0}
    [enng.nodes.remove(node) for node in enng.nodes if hasattr(node, 'zone') and (node.zone not in [c.name for c in eg.children] or scene.objects[node.zone].vi_params.envi_type == '1')]
         
    dcdict = {'Wall':(1, 1, 1, 1), 'Partition':(1, 1, 0, 1), 'Window':(0, 1, 1, 1), 'Roof':(0, 1, 0, 1), 'Ceiling':(1, 1, 0, 1), 'Floor':(0.44,0.185,0.07, 1), 'Shading':(1, 0, 0, 1)}
    ezdict = {'0': 'No_En_Net_Zone', '2': 'No_En_Net_TC'} 
    pva = 0
    linklist = []
    
    for coll in eg.children:
        cvp = coll.vi_params
        cvp['enparams'] = {}
        cvp['enparams']['floorarea'] = {}
        
        if coll.objects:
            for oi, obj in enumerate(coll.objects):
                done_mats = []
                ovp = obj.vi_params
                
                for k in ovp.keys():
                    if k not in ('envi_type', 'vi_type', 'envi_oca', 'envi_ica'):
                        del ovp[k]
#                ovp['enparams'] = {}
#                ovp['enparams']['floorarea'] = {}
                omats = [ms.material for ms in obj.material_slots]
        
                if ovp.envi_type in ('0', '2') and not omats:
                    op.report({'WARNING'}, 'Object {} is specified as a thermal zone but has no materials'.format(obj.name))
                elif None in omats:
                    op.report({'WARNING'}, 'Object {} has an empty material slot'.format(obj.name))

                # if ovp.envi_type in ('0', '2'):
                #     ofa = 0
                    
                #     for face in obj.data.polygons:
                #         if omats[face.material_index] and omats[face.material_index].vi_params.envi_nodes:                            
                #             for node in omats[face.material_index].vi_params.envi_nodes.nodes:
                #                 if node.bl_idname == 'No_En_Mat_Con' and node.active:
                #                     if node.envi_con_type =='Floor':
                #                         ofa += facearea(obj, face)
                #             omats[face.material_index].vi_params['enparams']['area'] += facearea(obj, face)
                
#                    ovp['enparams']["floorarea"][str(scene.frame_current)] = ofa
                                       
                for s, sm in enumerate(obj.material_slots): 
                    if sm.material and sm.material not in done_mats:
                        done_mats.append(sm.material)
                        mat = sm.material
                        mvp = mat.vi_params
                        
                        if mvp.envi_nodes and mvp.envi_nodes.name != mat.name:
                            mvp.envi_nodes = mvp.envi_nodes.copy()
                            mvp.envi_nodes.name = mat.name
                        
                        if mvp.envi_nodes and mvp.envi_nodes.users > 1:
                           mvp.envi_nodes.user_clear() 
                           mvp.envi_nodes = bpy.data.node_groups[mat.name]
                           
                        emnode = get_con_node(mvp)
                        
                        if not emnode:
                            op.report({'WARNING'}, 'The {} material has no node tree. This material has not been exported.'.format(mat.name))
                        elif any([n.use_custom_color for n in emnode.ret_nodes()]):
                            op.report({'ERROR'}, 'There is a red node in the {} material node tree. This material has not been exported.'.format(mat.name))
                            return
                        else:                       
                            emnode.ret_uv()
                            mct = 'Partition' if emnode.envi_con_con == 'Zone' else emnode.envi_con_type
                            mvp.envi_export = True    
    
                            if emnode.envi_con_type in dcdict:
                                mat.diffuse_color = dcdict[mct] 
                            if emnode.inputs['PV'].links:
                                mat.diffuse_color = (1, 1, 0, 1)
                         
            for link in enng.links:
                if link.from_socket.bl_idname in ('So_En_Net_Bound', 'So_En_Net_SFlow', 'So_En_Net_SSFlow'):
                    linklist.append([link.from_socket.node.name, link.from_socket.viuid, link.to_socket.node.name, link.to_socket.viuid])
                    enng.links.remove(link)
                    
            if context.view_layer.objects[coll.name].vi_params.envi_type != '1':
                if coll.name not in [node.zone for node in enng.nodes if hasattr(node, 'zone')]:
                    enng.nodes.new(type = ezdict[context.view_layer.objects[coll.name].vi_params.envi_type]).zone = coll.name
                else:
                    for node in enng.nodes:
                        if hasattr(node, 'zone') and node.zone == coll.name:
                            node.zupdate(bpy.context)
                        if hasattr(node, 'emszone') and node.emszone == coll.name:
                            node.zupdate(bpy.context) 
                        if hasattr(node, 'zone') and node.zone == coll.name:
                            node.uvsockupdate()    
            
            for node in enng.nodes:
                if [sock.bl_idname in ('So_En_Net_SFlow', 'So_En_Net_SFlow') for sock in node.inputs]:
                    enng['enviparams']['afn'] = 1
             
                if 'No_En_Net_ACon' not in [node.bl_idname for node in enng.nodes]:
                    enng.nodes.new(type = 'No_En_Net_ACon')         
                    enng.use_fake_user = 1
        else:
            bpy.data.collections.remove(coll)
    for ll in linklist:
        try:
            for outs in [o for o in enng.nodes[ll[0]].outputs if o.bl_idname in ('So_En_Net_Bound', 'So_En_Net_SFlow', 'So_En_Net_SSFlow')]:
                for ins in [i for i in enng.nodes[ll[2]].inputs if i.bl_idname in ('So_En_Net_Bound', 'So_En_Net_SFlow', 'So_En_Net_SSFlow')]:
                    if outs.viuid == ll[1] and ins.viuid == ll[3] and outs.bl_idname == ins.bl_idname:
                        enng.links.new(outs, ins)
                        print(outs.viuid, ins.viuid)

        except Exception as e:
            print('Link', e)
            
def writeafn(exp_op, en_idf, enng):
    if [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_ACon'] and not [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_Zone']:
        [enng.nodes.remove(enode) for enode in enng.nodes if enode.bl_idname == 'No_En_Net_ACon']

    for connode in [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_ACon']:
         en_idf.write(connode.epwrite(exp_op, enng))        

    for crnode in [enode for enode in enng.nodes if enode.bl_idname == 'EnViCrRef']:
        en_idf.write(crnode.epwrite())
        enng['enviparams']['crref'] = 1

    extnodes = [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_Ext']
    zonenodes = [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_Zone']
    ssafnodes = [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_SSFlow']
    safnodes = [enode for enode in enng.nodes if enode.bl_idname == 'No_En_Net_SFlow']

    if enng['enviparams']['wpca'] == 1:
        for extnode in extnodes:
            en_idf.write(extnode.epwrite(enng))
    for enode in zonenodes:
        en_idf.write(enode.epwrite())
    for enode in ssafnodes + safnodes:
        en_idf.write(enode.epwrite(exp_op, enng))
