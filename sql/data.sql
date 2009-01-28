insert into os_list values (NULL,"WINNT 5.1");
insert into os_list values (NULL,"WINNT 6.0");
insert into os_list values (NULL,"MacOSX Darwin 8.8.1");
insert into os_list values (NULL,"MacOSX Darwin 9.2.2");
insert into os_list values (NULL,"Ubuntu 7.10");

insert into branches values (NULL,"Firefox");
insert into branches values (NULL,"Firefox3.0");
insert into branches values (NULL,"Firefox3.1");
insert into branches values (NULL,"TraceMonkey");
insert into branches values (NULL,"Fennec");

-- osid,cpuspeed,isthrottling,name,isactive,dateadded
insert into machines values (NULL,1,"1.63",0,"qm-pxp-stage01",1,unix_timestamp());
insert into machines values (NULL,2,"1.63",0,"qm-pvista-stage01",1,unix_timestamp());
insert into machines values (NULL,3,"1.63",0,"qm-ptiger-stage01",1,unix_timestamp());
insert into machines values (NULL,4,"1.63",0,"qm-pleopard-stage01",1,unix_timestamp());
insert into machines values (NULL,5,"1.63",0,"qm-pubuntu-stage01",1,unix_timestamp());

insert into pagesets values (NULL,"Tp December, 2006 (393 pages)");
insert into pagesets values (NULL,"Tp November, 2000 (40 pages)");
insert into pagesets values (NULL,"DHTML");
insert into pagesets values (NULL,"GFX");
insert into pagesets values (NULL,"SVG");
insert into pagesets values (NULL,"Dromaeo");
insert into pagesets values (NULL,"SunSpider");

-- name,prettyname,ischrome,isactive,pagesetid
insert into tests values (NULL,"tp_nochrome","Tp3 NoChrome",0,1,1);
insert into tests values (NULL,"tp","Tp3",1,1,1);
insert into tests values (NULL,"tp_pbytes", "Tp3 (Private Bytes)",1,1,NULL);
insert into tests values (NULL,"tp_pbytes_nochrome","Tp3 NoChrome (Private Bytes)",0,1,NULL);
insert into tests values (NULL,"tp_rss","Tp3 (RSS)",1,1,NULL);
insert into tests values (NULL,"tp_rss_nochrome","Tp3 NoChrome (RSS)",0,1,NULL);
insert into tests values (NULL,"tp_%cpu","Tp3 (%CPU)",1,1,NULL);
insert into tests values (NULL,"tp_%cpu_nochrome","Tp3 NoChrome (%CPU)",0,1,NULL);
insert into tests values (NULL,"tp_memset","Tp3 (Memset)",1,1,NULL);
insert into tests values (NULL,"tp_memset_nochrome","Tp3 NoChrome (Memset)",0,1,NULL);
insert into tests values (NULL,"tp_fast","Tp3 Fast Cycle",1,1,2);
insert into tests values (NULL,"ts","Ts",1,1,NULL);
insert into tests values (NULL,"twinopen","Txul",1,1,NULL);
insert into tests values (NULL,"tdhtml","DHTML",1,1,3);
insert into tests values (NULL,"tdhtml_nochrome","DHTML NoChrome",0,1,3);
insert into tests values (NULL,"tgfx","GFX",1,1,4);
insert into tests values (NULL,"tgfx_nochrome","GFX NoChrome",0,1,4);
insert into tests values (NULL,"tsvg","SVG",1,1,5);
insert into tests values (NULL,"tsvg_nochrome","SVG NoChrome",0,1,5);
insert into tests values (NULL,"tjss","Dromaeo",1,1,6);
insert into tests values (NULL,"tsspider","SunSpider",1,1,7);
insert into tests values (NULL,"tsspider_nochrome","SunSpider NoChrome",0,1,7);
