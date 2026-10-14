-- Laser_gen (Historial de tratamientos) tabla fichamedica primera tabla creada 

SELECT 
p.personaID,
p.nombre,
p.apellido1,
p.apellido2,
 f.*
from fichamedica as f
Join person_dup as p
on f.codpersona = p.codpersona
where personaID = 5;

-----

SELECT 
p.personaID,
p.nombre,
p.apellido1,
p.apellido2,
 det.*
from detallealbaranhistorico as det
Join person_dup as p
on det.codpersona = p.codpersona
Where personaID= 5;


select * from detallealbaranhistorico;

-- NEW Laser_gen (Historial de tratamientos) con detallealbaran, segunda tabla creada con codigotrat 

SELECT 
p.personaID,
p.nombre,
p.apellido1,
p.apellido2,
map.codigotrat,
map.ProductID  as LaserZoneID,
 deta.*
from detallealbaran as deta
Join person_dup as p
on deta.codpersona = p.codpersona
left join product_map as map
on deta.codigotrat = map.codigotrat
where personaID =5;

SELECT 
p.personaID,
p.nombre,
p.apellido1,
p.apellido2,
 deta.*
from detallealbaran as deta
Join person_dup as p
on deta.codpersona = p.codpersona;


---- Join con historiaclinica n

SELECT 
p.personaID,
p.nombre,
p.apellido1,
p.apellido2,
 hist.*
from historiaclinica as hist
Join person_dup as p
on hist.codpersona = p.codpersona;






where personaID = 32;

select * from detallealbaran;


select * from tratamientos;

select * from product_map
Where codigotrat = 'DERMA';






