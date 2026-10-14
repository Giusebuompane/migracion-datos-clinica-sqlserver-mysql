


-- Queiry historia clinica (Clients_crm)
SELECT 
p.personaID,
p.nombre,
p.apellido1,
p.apellido2,
 h.*
 from historiaclinica as h
 join person_dup as p
on h.codpersona = p.codpersona
where personaID = 3854;


-- Incremento client_crm con fichamedica

SELECT 
    p.personaID,
    p.nombre,
    p.apellido1,
    p.apellido2,
    f.*
FROM  fichamedica AS f
JOIN person_dup AS p
    ON f.codpersona = p.codpersona
    where personaID = 177;


    -- Join con trmient (NO)

  SELECT 
    p.personaID,
    p.nombre,
    p.apellido1,
    p.apellido2,
    f.*
FROM  trmient AS f
JOIN person_dup AS p
    ON f.codpersona = p.codpersona
    where personaID = 3854;

      SELECT 
    p.personaID,
    p.nombre,
    p.apellido1,
    p.apellido2,
    f.*
FROM  detallepresupuesto AS f
JOIN person_dup AS p
    ON f.codpersona = p.codpersona
    where personaID = 3854;