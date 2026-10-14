-- Consulta tabla multimedia,(CSV files'pictures)

SELECT 
p.personaID as FileClientID,
p.nombre, 
p.apellido1, 
p.apellido2,
m.nombrearchivo as FileName,
CONCAT('FILES/',p.codnumpersona,'/',m.nombrearchivo)  as FilePath,
m.fechacreacion as FileDate
FROM multimedia m
left join person_dup p 
	on p.codpersona=m.codpersona
WHERE personaID = 115



-- Consulta para python


SELECT 
p.personaID as FileClientID_PictureClientID,
m.nombrearchivo as FileName,
CONCAT('ficheros/',p.codnumpersona,'/',m.nombrearchivo)  as FilePath_PicturePath,
CAST(m.fechacreacion as date) as FileDate_PictureDate
FROM multimedia m
left join person_dup p 
	on p.codpersona=m.codpersona
WHERE personaID is not null




with files as (SELECT 
p.personaID as FileClientID,
p.nombre, 
p.apellido1, 
p.apellido2,
m.nombrearchivo,
CONCAT('ficheros/',p.codnumpersona,'/',m.nombrearchivo)  as FilePath_PicturePath,
m.fechacreacion as FileDate
FROM multimedia m
left join person_dup p 
	on p.codpersona=m.codpersona)
select * from files 
Where FileClientID =  3150 ;                            -- 1738
 -- where FilePath_PicturePath like '%_APELLIDO.jpg%'

 select * from person_dup
 where PersonaID = 3150


 select * from persona
 where codpersona = 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX'
