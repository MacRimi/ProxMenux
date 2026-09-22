"""Build separate update/recreate proposals without mutating live contracts."""
import copy


def propose(instance, operation, current_template=None, edited_deployment=None):
    if operation not in ('update', 'recreate'):
        raise ValueError('Operacion no soportada')
    if instance.get('status') != 'installed':
        raise ValueError('La instancia no esta completada')
    if operation == 'update' and (current_template is not None or edited_deployment is not None):
        raise ValueError('Actualizar no puede modificar la configuracion; usa Recrear')
    candidate = copy.deepcopy(instance)
    if operation == 'recreate':
        if current_template is None or edited_deployment is None:
            raise ValueError('Recrear requiere la plantilla actual y la configuracion confirmada')
        if current_template['id'] != instance['template']['id']:
            raise ValueError('No se puede sustituir silenciosamente la aplicacion')
        if edited_deployment.get('vmid') != instance['vmid']:
            raise ValueError('Recrear conserva la identidad y el VMID')
        candidate['template'] = copy.deepcopy(current_template)
        candidate['deployment'] = copy.deepcopy(edited_deployment)
    old = {m['container_path']: m for m in instance['deployment'].get('mounts', [])}
    new = {m['container_path']: m for m in candidate['deployment'].get('mounts', [])}
    if len(new) != len(candidate['deployment'].get('mounts', [])):
        raise ValueError('Rutas duplicadas')
    changed_storage = [p for p in old.keys() & new.keys()
                       if (old[p].get('type'), old[p].get('source')) !=
                          (new[p].get('type'), new[p].get('source'))]
    return {'operation': operation, 'installation_id': instance['installation_id'],
            'candidate': candidate, 'requires_confirmation': True,
            'mounts': {'reuse': sorted(old.keys() & new.keys() - set(changed_storage)),
                       'add': sorted(new.keys() - old.keys()),
                       'detach_without_delete': sorted(old.keys() - new.keys()),
                       'storage_change_requires_migration': sorted(changed_storage)},
            'execution_enabled': False}
