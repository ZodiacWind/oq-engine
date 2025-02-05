Scenario QA Test for contents
=============================

============== ===================
checksum32     253,980,831        
date           2017-12-06T11:21:21
engine_version 2.9.0-gite55e76e   
============== ===================

num_sites = 3, num_imts = 3

Parameters
----------
=============================== ==================
calculation_mode                'scenario'        
number_of_logic_tree_samples    0                 
maximum_distance                {'default': 300.0}
investigation_time              None              
ses_per_logic_tree_path         1                 
truncation_level                3.0               
rupture_mesh_spacing            10.0              
complex_fault_mesh_spacing      10.0              
width_of_mfd_bin                None              
area_source_discretization      None              
ground_motion_correlation_model None              
random_seed                     3                 
master_seed                     0                 
=============================== ==================

Input files
-----------
====================== ======================================================================
Name                   File                                                                  
====================== ======================================================================
contents_vulnerability `vulnerability_model_contents.xml <vulnerability_model_contents.xml>`_
exposure               `exposure_model.xml <exposure_model.xml>`_                            
job_ini                `job_haz.ini <job_haz.ini>`_                                          
rupture_model          `fault_rupture.xml <fault_rupture.xml>`_                              
====================== ======================================================================

Composite source model
----------------------
========= ====== =============== ================
smlt_path weight gsim_logic_tree num_realizations
========= ====== =============== ================
b_1       1.000  trivial(1)      1/1             
========= ====== =============== ================

Realizations per (TRT, GSIM)
----------------------------

::

  <RlzsAssoc(size=1, rlzs=1)
  0,ChiouYoungs2008(): [0]>

Exposure model
--------------
=============== ========
#assets         3       
#taxonomies     3       
deductibile     absolute
insurance_limit absolute
=============== ========

======== ===== ====== === === ========= ==========
taxonomy mean  stddev min max num_sites num_assets
RC       1.000 NaN    1   1   1         1         
RM       1.000 NaN    1   1   1         1         
W        1.000 NaN    1   1   1         1         
*ALL*    1.000 0.0    1   1   3         3         
======== ===== ====== === === ========= ==========

Slowest operations
------------------
======================= ========= ========= ======
operation               time_sec  memory_mb counts
======================= ========= ========= ======
reading exposure        0.007     0.0       1     
reading site collection 7.391E-06 0.0       1     
======================= ========= ========= ======