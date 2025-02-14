# Write EMD 1.0 formatted HDF5 files.

import h5py
import numpy as np
from warnings import warn
from os.path import exists,basename
from os import remove
from uuid import uuid4
from emdfile.read import _is_EMD_file, _get_EMD_rootgroups
from emdfile.classes.utils import EMD_data_group_types
from emdfile.classes import (
    Node,
    Root,
    Array,
    Metadata
)


def write(
    filepath,
    data,
    mode = 'w',
    emdpath = None,
    tree = True,
    ):
    """
    Saves data to a .h5 file at filepath. Specific behavior depends on the
    `data`, `mode`, `tree`, and `emdpath` arguments.

    Calling

        >>> save(path, data)

    if `data` is a Root instance saves this root and its entire tree to a new
    file. If `data` is any other type of rooted node (i.e. a node inside of
    some runtime data tree), this code writes a new file with a single tree
    using this node's root (even if this node is far downstream of the root
    node), placing this node and the tree branch underneath it inside that
    root. In both cases, the root metadata is stored in the new H5 root node.
    If `data` is an unrooted node (i.e. a freestanding node not connected to
    a tree), this code creates a new root node with no metadata and this node's
    name, and places this node inside that root in a new file.

    If `data` is a numpy array or Python dictionary, wraps data in either an
    emd.Array or emd.Metadata instance, assigns the name 'np.array' or
    'dictionary', places the object in a root of this name and saves. If
    `data` is a list of objects which are all numpy arrays, Python dictionaries,
    or emd.Node instances, places all these objects into a single root, assigns
    the roots name according to the first object in the list, and saves.

    To write a single node from a tree,  set `tree` to False. To write the
    tree underneath a node but exclude the node itself set `tree` to None.

    To add to an existing EMD file, use the `mode` argument to set append or
    appendover mode. If the `emdpath` variable is not set and `data` has a
    runtime root that does not exist in the EMD root groups already present,
    adds the new root and writes as described above. If `emdpath` is not set
    and the runtime root group matches a root group that's already present,
    this function performs a diff operation between the root metadata and
    data nodes from `data` and those already in the H5 file. Append mode adds
    any data/metadata groups with no equivalent (i.e. same name and tree
    location) in the H5 tree, while skipping any data/metadata already found
    in the tree. Appendover adds any data/metadata with no equivalent already
    in the H5 tree, and overwrites any data/metadata groups that are already
    represented in the HDF5 with the new data. Note that this function does
    not attempt to take a diff between the contents of the groups and the
    runtime data groups - it only considers the names and their locations in
    the tree. If append or appendover mode are used and filepath is set to
    a location that does not already contain a file on the filesystem,
    behavior is identical to write mode. When appendover mode overwrites
    data, it is erasing the old links and creating new links to new data;
    however, the HDF5 file does not release the space on the filesystem.
    To free up storage, set mode to 'appendover', and this function will
    add a final step to re-write then delete the old file.

    The `emdpath` argument is used to append to a specific location in an
    extant EMD file downstream of some extant root. If passed, it must point
    to a valid location in the EMD file. This function will then perform a
    diff and write as described in the prior paragraph, except beginning
    from the H5 node specified in `emdpath`. Note that in this case the root
    metadata is still compared to and added or overwritten in the H5 root node,
    even if the remaining data is being added to some downstream branch.


    Args:
        filepath: path where the file will be saved
        data: an EMD data class instance
        mode (str): supported modes and their keys are:
                - write ('w','write')
                - overwrite ('o','overwrite')
                - append ('a','+','append')
                - appendover ('ao','oa','o+','+o','appendover')
            Write mode writes a new file, and raises an exception if a file
            of this name already exists.  Overwrite mode deletes any file of
            this name that already exists and writes a new file. Append and
            appendover mode write a new file if no file of this name exists,
            or if a file of this name does exist, adds new data to the file.
            The specific behavior of append and appendover depend on the
            `data`,`emdpath`, and `tree` arguments as discussed in more detail
            above. Broadly, both modes attempt to detemine the difference
            between the data passed and that present in the extent HDF5 file
            tree, add any data not already in the H5, and then either skips
            or overwrites conflicting nodes in append or appendover mode,
            respectively.
        tree: indicates how the object tree nested inside `data` should
            be treated.  If `True` (default), the entire tree is saved.
            If `False`, only this object is saved, without its tree. If
            `None`, saves the entire tree underneath `data`, but not
            the node at `data` itself.
        emdpath (str or None): optional parameter used in conjunction with
            append or appendover mode; if passed in write or overwrite mode,
            this argument is ignored. Indicates where in an existing EMD
            file tree to place the data. Must be a '/' delimited string
            pointing to an existing EMD file tree node.
    """
    # parse mode
    writemode = [
        'w',
        'write'
    ]
    overwritemode = [
        'o',
        'overwrite'
    ]
    appendmode = [
        'a',
        '+',
        'append'
    ]
    appendovermode = [
        'oa',
        'ao',
        'o+',
        '+o',
        'appendover'
    ]
    allmodes = writemode + overwritemode + appendmode + appendovermode

    # emdpath implies append mode
    if emdpath is not None and mode not in appendovermode:
        mode = 'a'


    # validate `mode` and `tree` inputs
    er = f"unrecognized mode {mode}; mode must be in {allmodes}"
    assert(mode in allmodes), er
    if tree == 'noroot':
        warn("`tree = 'noroot'` is deprecated and will be removed in a future version. Use `tree = None` instead.")
        tree = None
    assert(tree in (True,False,None)), f"invalid value {tree} passed for `tree`"
    if mode in writemode:
        assert(not(exists(filepath))), "A file already exists at this destination; use append or overwrite mode, or choose a new file path."


    # validate `data` inputs, and
    # handle non-Node `data` inputs

    # numpy array -> Array
    if isinstance(data, np.ndarray):
        root = Root(name='root')
        data = Array(name='np.array',data=data)
        root.add_to_tree(data)

    # dictionaries -> Metadata
    elif isinstance(data, dict):
        root = Root(name='root')
        md = Metadata(name='dictionary',data=data)
        root.metadata = md
        data = root

    # for lists...
    elif isinstance(data, (list,tuple)):
        assert(all( [isinstance(x,(np.ndarray,dict,Node)) for x in data] )), \
            "can only save np.array, dictionary, or emd.Node objects"

        # ...save lists of Roots as multiple EMD trees
        if any([isinstance(x,Root) for x in data]):
            assert(all([isinstance(x,Root) for x in data])), \
            "if saving a list containing a Root, all list elements must be Roots"
            # save the first root with a call to save, then
            # change to append mode and save other roots
            write(
                filepath,
                data[0],
                mode=mode,
                tree=tree
            )
            if mode in writemode:
                mode = 'a'
            elif mode in overwritemode:
                mode = 'ao'
            for x in data[1:]:
                write(
                    filepath,
                    x,
                    mode=mode,
                    tree=tree
                )
            return

        # ...otherwise store all list elements in a single tree...
        root = Root(name='root')
        ar_ind,md_ind = 0,0
        for d in data:

            # ...with numpy arrays as Arrays
            if isinstance(d,np.ndarray):
                d = Array(name=f'np.array_{ar_ind}',data=d)
                ar_ind += 1
                root.add_to_tree(d)

            # ...dictionaries as Metadata
            elif isinstance(d,dict):
                d = Metadata(name=f'dictionary_{md_ind}',data=d)
                md_ind += 1
                root.metadata = d

            # ...and Nodes as themselves
            else:
                assert(isinstance(d,Node)), f"invalid data type in `data` list, {type(d)}"
                root.add_to_tree(d)
        data = root

    # `data` should now be a Node!
    assert(isinstance(data,Node)), f"invalid type {type(data)} found for `data`"

    # handle rootless data
    added_a_root = False
    if data._root is None:
        added_a_root = True
        root = Root(name=data.name)
        root.add_to_tree(data)
    else:
        # get the root
        root = data.root



    # overwrite mode - delete existing file
    if mode in overwritemode:
        if exists(filepath):
            remove(filepath)
        mode = 'w'



    # write a new file
    if mode in writemode or (
        mode in appendmode+appendovermode and not exists(filepath)):


        # open the file
        with h5py.File(filepath, 'w') as f:

            # write header
            _write_header(
                file = f
            )

            # write the file
            _write_from_root(
                file = f,
                root = root,
                data = data,
                tree = tree
            )



    # append to an existing file
    else:

        # validate that its an EMD file
        # get the rootgroups
        assert(_is_EMD_file(filepath)), "{filepath} does not point to an EMD 1.0 file"
        emd_rootgroups = _get_EMD_rootgroups(filepath)

        # open the file
        with h5py.File(filepath, 'a') as f:



            # if the root doesn't already exist and emdpath is None,
            # do a simple write as above
            if not(root.name in emd_rootgroups) and (emdpath is None):

                _write_from_root(
                    file = f,
                    root = root,
                    data = data,
                    tree = tree
                )



            # if the root doesn't already exist and emdpath is specified,
            # append the data to the target node
            elif not(root.name in emd_rootgroups):

                # parse emdpath
                if emdpath[0] == '/':
                    emdpath = emdpath[1:]
                l = emdpath.split('/')
                rootname = l[0]
                treepath = '/'.join(l[1:])

                # get the rootgroup
                assert(rootname in f.keys()), f"No root called {rootname} found - check your `emdpath`"
                rootgroup = f[rootname]

                # validate the emdpath
                # set target_grp to targeted EMD node
                where = _validate_treepath(
                    rootgroup,
                    treepath
                )
                #print(treepath)
                #print(data._treepath)
                #print(where)
                #print(where[0].name)
                if where is False:
                    raise Exception(f"No node found at {emdpath} in the EMD tree called {rootname} - check your `emdpath`")
                elif where[1] is False:
                    raise Exception(f"No node found at {emdpath} in the EMD tree called {rootname} - check your `emdpath`")
                else:
                    target_grp = where[0]


                # append to the tree...

                # ...if data is Root and tree is False
                if isinstance(data,Root) and (tree is False):
                    raise Exception("Incompatible inputs: if appending from a Root to an existing tree, `tree` can't be False.  Try changing `data` or `tree`.")

                # ...if data is Root and tree is True or None
                elif isinstance(data,Root):
                    _write_tree(
                        target_grp,
                        data
                    )

                # ...if data is a Node and tree is False
                elif tree is False:
                    _write_single_node(
                        target_grp,
                        data
                    )

                # ...if data is a Node and tree is True
                elif tree is True:
                    target_grp = _write_single_node(
                        target_grp,
                        data
                    )
                    _write_tree(
                        target_grp,
                        data
                    )

                # ...if data is a Node and tree is None
                else:
                    _write_tree(
                        target_grp,
                        data
                    )



            # if the root does exist and emdpath is None,
            # peform diffmerge A
            elif emdpath is None:

                # choose how to handle conflicts
                appendover = True if mode in appendovermode else False

                # get the rootgroup
                rootgroup = f[root.name]

                # compare/append root metadata
                _append_root_metadata(
                    rootgroup = rootgroup,
                    root = root,
                    appendover = appendover
                )


                # choose behavior and write...
                if data is root:
                    # ...if the data is the root
                    if tree is True:
                        _append_branch(
                            rootgroup,
                            data,
                            appendover
                        )
                    else:
                        pass

                else:
                    where = _validate_treepath(
                        rootgroup,
                        data._treepath
                    )
                    # ...if the datapath is not in the H5 path
                    if where is False:
                        raise Exception("The data passed can't be added to it's corresponding H5 tree - check that the data's `_treepath` is present in the existing EMD file")
                    else:
                        where,inside = where
                        # ...if the datapath is in the H5 path
                        if inside is True:
                            if tree is True:
                                if appendover:
                                    next_node = _overwrite_single_node(
                                        where,
                                        data
                                    )
                                else:
                                    next_node = where
                                _append_branch(
                                    next_node,
                                    data,
                                    appendover
                                )
                            elif tree is False:
                                if appendover:
                                    next_node = _overwrite_single_node(
                                        where,
                                        data
                                    )
                                else:
                                    pass
                            else:
                                _append_branch(
                                    where,
                                    data,
                                    appendover
                                )
                        # ...if the datapath is one node beyond the H5 path
                        else:
                            if tree is True:
                                new_node = _write_single_node(
                                    where,
                                    data
                                )
                                _write_tree(
                                    new_node,
                                    data
                                )
                            elif tree is False:
                                _write_single_node(
                                    where,
                                    data
                                )
                                pass
                            else:
                                _write_tree(
                                    where,
                                    data
                                )



            # if the root does exist and emdpath is specified,
            # peform diffmerge B
            else:

                # choose how to handle conflicts
                appendover = True if mode in appendovermode else False

                # parse emdpath
                if emdpath[0] == '/':
                    emdpath = emdpath[1:]
                l = emdpath.split('/')
                rootname = l[0]
                treepath = '/'.join(l[1:])

                # get the rootgroup
                rootgroup = f[root.name]

                # validate the emdpath
                # set target_grp to targeted EMD node
                where = _validate_treepath(
                    rootgroup,
                    treepath
                )
                if where is False:
                    raise Exception(f"No node found at {emdpath} in the EMD tree called {rootname} - check your `emdpath`")
                elif where[1] is False:
                    raise Exception(f"No node found at {emdpath} in the EMD tree called {rootname} - check your `emdpath`")
                else:
                    target_grp = where[0]


                # compare/append root metadata
                _append_root_metadata(
                    rootgroup = rootgroup,
                    root = root,
                    appendover = appendover
                )



                # choose behavior and write...

                # ...if the data is the root
                if data is root:

                    # Confirm that the target node is downstream of the root...
                    assert(rootgroup.__contains__(target_grp.name)), "Specified target node not found in the EMD file - check your emdpath."

                    # get the path from source to target, then
                    # move `data` to the target node point
                    path_to_target = target_grp.name.replace(rootgroup.name,'')[1:]
                    try:
                        data = data.tree(path_to_target)
                    except AssertionError:
                        raise Exception("Append failure - the target EMD node exists downstream of the source EMD node, however the target is not present in the corresponding runtime tree")
                    # write
                    if appendover and tree in (True,False):
                        target_grp = _overwrite_single_node(
                            target_grp,
                            data
                        )
                    if tree in (True,None):
                        _append_branch(
                            target_grp,
                            data,
                            appendover
                        )


                # ...if the data is a node...
                else:
                    # validate the source node path
                    where = _validate_treepath(
                        rootgroup,
                        data._treepath
                    )
                    # ...if the source node is not in the H5
                    if where is False:
                        raise Exception("The data passed can't be appended to it's corresponding H5 tree - the source runtime node can't be matched to the existing tree")
                    else:
                        source_grp,inside = where

                        # ...if the source node is one node beyond the H5
                        if inside is False:
                            # ...if it is one node past the targetted node, write
                            if source_grp.name == target_grp.name:
                                if tree in (True,None):
                                    _append_branch(
                                        target_grp,
                                        data,
                                        appendover
                                    )
                                else:
                                    _write_single_node(
                                        target_grp,
                                        data
                                    )
                            # ...otherwise, raise an Exception
                            else:
                                raise Exception("The data passed can't be added to it's corresponding H5 tree - check that the data's `.tree()` path is present in the existing EMD file")

                        # ...if the source node is in inside the H5
                        else:
                            # ...if the source node is the target node, write
                            if source_grp.name == target_grp.name:
                                if appendover and tree in (True,False):
                                    target_grp = _overwrite_single_node(
                                        target_grp,
                                        data
                                    )
                                if tree in (True,None):
                                    _append_branch(
                                        target_grp,
                                        data,
                                        appendover
                                    )
                            # ...if the source node is one node downstream of the target, write
                            elif basename(source_grp.name) in list(target_grp.keys()):
                                target_grp = source_grp
                                if appendover and tree in (True,False):
                                    target_grp = _overwrite_single_node(
                                        target_grp,
                                        data
                                    )
                                if tree in (True,None):
                                    _append_branch(
                                        target_grp,
                                        data,
                                        appendover
                                    )
                            # ...if the target node is downstream of the source node...
                            elif source_grp.__contains__(target_grp.name):
                                # get the path from source to target, then
                                # move `data` to the target node point
                                path_to_target = target_grp.name.replace(source_grp.name,'')[1:]
                                try:
                                    data = data.tree(path_to_target)
                                except AssertionError:
                                    raise Exception("Append failure - the target EMD node exists downstream of the source EMD node, however the target is not present in the corresponding runtime tree")
                                # write
                                if appendover and tree in (True,False):
                                    target_grp = _overwrite_single_node(
                                        target_grp,
                                        data
                                    )
                                if tree in (True,None):
                                    _append_branch(
                                        target_grp,
                                        data,
                                        appendover
                                    )

                            # ...otherwise raise an exception
                            else:
                                raise Exception("Append failure - target node may not be downstream of source node.  Check the emdpath and the runtime data tree.")




    # if a root was added, remove it
    if added_a_root:
        data._root = None


    # end
    pass






# Utilities

def _write_header(
    file
    ):
    from emdfile import _PROGRAM_NAME, _USER_NAME
    file.attrs.create("emd_group_type",'file')
    file.attrs.create("version_major",1)
    file.attrs.create("version_minor",0)
    #file.attrs.create("version_release",0)
    file.attrs.create("UUID",str(uuid4()))
    file.attrs.create("authoring_program",_PROGRAM_NAME)
    file.attrs.create("authoring_user",_USER_NAME)


def _write_from_root(
    file,
    root,
    data,
    tree
    ):
    """ From an open h5py File with an EMD 1.0 header, adds a new root
    and data tree
    """
    # write the root
    rootgroup = _write_single_node(
        group = file,
        data = root,
    )
    rootgroup.attrs['emd_group_type'] = 'root'

    # write the rest
    if data is root:
        if tree is False:
            pass
        else:
            _write_tree(
                group=rootgroup,
                data=data
            )
    else:
        if tree is False:
            grp = _write_single_node(
                group = rootgroup,
                data = data
            )
        elif tree is True:
            grp = _write_single_node(
                group = rootgroup,
                data = data
            )
            _write_tree(
                group = grp,
                data = data
            )
        else:
            _write_tree(
                group = rootgroup,
                data = data
            )


def _write_single_node(
    group,
    data
    ):
    grp = data.to_h5(group)
    return grp


def _write_tree(
    group,
    data
    ):
    """ Writes the data tree underneath `data`; does not write `data`
    """
    for k in data._branch.keys():
        grp = _write_single_node(
            group = group,
            data = data._branch[k]
        )
        _write_tree(
            grp,
            data._branch[k]
        )


def _append_root_metadata(
    rootgroup,
    root,
    appendover
    ):
    # Determine if there is new group metadata
    if len(root._metadata)==0:
        return
    # Get file root metadata groups
    metadata_groups = []
    if "metadatabundle" not in rootgroup.keys():
        mdbundle_group = rootgroup.create_group('metadatabundle')
    else:
        mdbundle_group = rootgroup['metadatabundle']
        for k in mdbundle_group.keys():
            if "emd_group_type" in mdbundle_group[k].attrs.keys():
                if mdbundle_group[k].attrs["emd_group_keys"] == "metadata":
                    metadata_groups.append(k)
    # loop
    for key in root._metadata:
        # if this group already exists
        if key in metadata_groups:
            # overwrite it
            if appendover:
                del(mdbundle_group[key])
                root._metadata[key].to_h5(mdbundle_group)
            # or skip it
            else:
                pass
        # otherwise, write it
        else:
            root._metadata[key].to_h5(mdbundle_group)
    return


def _validate_treepath(
    rootgroup,
    treepath
    ):
    """
    Accepts a file rootgroup and a runtime `treepath` string.
    If the treepath is not in the file, returns False.
    If the treepath is in the file, returns (grp, True) and
    if the treepath is one node beyond the file, returns (grp, False),
    where `grp` is the final h5py Group on treepath in the file tree.
    """
    grp_names = treepath.split('/')
    try:
        grp_names.remove('')
    except ValueError:
        pass
    group = rootgroup
    for i,name in enumerate(grp_names):
        if name not in group.keys():
            # catch for being one node beyond
            if i == len(grp_names)-1:
                return group, False
            return False
        group = group[name]
        try:
            assert(isinstance(group,h5py.Group))
        except AssertionError:
            return False
    return group, True


def _overwrite_single_node(
    group,
    data
    ):
    # get names
    groupname = group.name.split('/')
    name = groupname[-1]
    rootname = '/'+groupname[1]
    groupname = '/'+'/'.join(groupname[2:])

    # Validate
    assert(data.name == name), f"Can't overwrite - data/group names don't match: {data.name} != {name}"
    assert(groupname == data._treepath), f"Can't overwrite - data/group paths dont match: {group.name != data._treepath}"

    # Get parent group
    parentpath = data._treepath.split('/')
    parentpath = rootname+'/'.join(parentpath[:-1])
    parentgroup = group.file[parentpath]

    # Rename the old group
    parentgroup.move(name,"_tmp_"+name)

    # Write the new data 
    new_group = _write_single_node(
        parentgroup,
        data
    )

    # Copy the links
    keys = [k for k in group.keys() if "emd_group_type" in group[k].attrs.keys()]
    keys = [k for k in keys if group[k].attrs["emd_group_type"] in EMD_data_group_types]
    for key in keys:
        new_group[key] = group[key]

    # Remove the old group
    del(parentgroup["_tmp_"+name],group)

    # Return
    return new_group


def _append_branch(
    group,
    data,
    appendover
    ):
    groupkeys = [k for k in group.keys() if "emd_group_type" in group[k].attrs.keys()]
    # for each node under `data`...
    for key in data._branch.keys():
        d = data._branch[key]
        # ...if this node doesn't exist in the H5, do a simple write
        if d.name not in groupkeys:
            _write_single_node(
                group,
                d
            )
            _write_tree(
                group,
                d
            )
        # otherwise, overwrite or skip it, then call this fn again
        else:
            if appendover:
                next_node = _overwrite_single_node(
                    group[key],
                    d
                )
            else:
                next_node = group[key]
            _append_branch(
                next_node,
                d,
                appendover
            )


