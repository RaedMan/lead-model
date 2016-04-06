create temp table wic as (
with 

kid_addresses_summary as (
	select kid_id,
		sum(('2016-01-25'::date - address_max_date < 6*30)::int) as address_count_6m
	from output.kid_addresses
	where address_wic_infant
	and kid_id in (select kid_id from predictions)
	group by kid_id
),

kid_address_summary AS (

select kid_id,
	array_remove(array_agg(distinct i.part_id_i), null) part_id_i,
	array_remove(array_agg(distinct i.brth_lst_t), null) brth_lst_t, 
	array_remove(array_agg(distinct i.brth_fst_t), null) brth_fst_t, 
	array_remove(array_agg(distinct i.birth_d), null) birth_d, 

	array_remove(array_agg(distinct coalesce(addr_ln1_t, '') || ' ' || coalesce(addr_ln2_t, '') || ' ' || coalesce(addr_apt_t, '')), null) addr,
	array_remove(array_agg(distinct cont_nme_t), null) cont_nme_t, 
	array_remove(array_agg(distinct relate_c), null) relate_c,
        array_remove(array_agg(distinct phne_nbr_n), null) phne_nbr_n,

	array_remove(array_agg(distinct m.part_id_i), null) mothr_part_id_i,
	array_remove(array_agg(distinct m.brth_lst_t), null) mothr_brth_lst_t, 
	array_remove(array_agg(distinct m.brth_fst_t), null) mothr_brth_fst_t
from predictions
left join aux.kid_wics using (kid_id)
left join cornerstone.partenrl i using (part_id_i)
left join cornerstone.partaddr on i.part_id_i = addr_id_i 
left join aux.kid_mothers using (kid_id)
left join cornerstone.partenrl m on m.part_id_i = kid_mothers.mothr_id_i
group by 1)

select *, kid_id in (1808612,  956261,  627754,  482377,  634444,  333094,  333094) as moved
From predictions p
left join kid_addresses_summary k2 using (kid_id) 
left join kid_address_summary k1 using (kid_id)
);

-- select top 75 
-- pilot is boolean of participation in pilot
create temp table pilot01_top as (select distinct on (kid_id) *, false as pilot from wic where kid_id in (select kid_id from wic where age + 50 between 30*11 and 365 order by score desc limit 75) order by kid_id, score desc);

select setseed(0.772171495482326);
update pilot01_top set pilot = true where kid_id in (select kid_id from pilot01_top order by random() limit 37);

select setseed(0.772171495482326);
create temp table pilot01_rest as (select *, true as pilot from wic where age + 50 between 30*11 and 365 order by random() limit 10);

\copy (select * from (select * from pilot01_top UNION ALL select * from pilot01_rest where kid_id not in (select kid_id from pilot01_top)) t order by score desc) to data/pilot/01.csv with csv header;

select setseed(0.772171495482326);

\copy (select * from ((select * from pilot01_top where pilot and not moved limit 25) UNION ALL (select * from pilot01_rest where kid_id not in (select kid_id from pilot01_top) and pilot and not moved limit 5)) t order by random()) to data/pilot/01_pilot.csv with csv header;
