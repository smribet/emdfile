# Defines a class, PointList, for storing / accessing / manipulating data
# in the form of lists of vectors in named dimensions.  Wraps numpy
# structured arrays.

import numpy as np
import h5py
from typing import Optional
from os.path import basename

from emdfile.classes.tree import Node


class PointList(Node):
    """
    A wrapper around structured numpy arrays, with read/write functionality in/out of
    EMD formatted HDF5 files.

    """
    _emd_group_type = 'pointlist'

    def __init__(
        self,
        data: np.ndarray,
        name: Optional[str] = 'pointlist',
        ):
        """
		Instantiate a PointList.

        Args:
            data (structured numpy ndarray): the data; the dtype of this array will
                specify the fields of the PointList.
            name (str): name for the PointList

        Returns:
            a PointList instance
        """
        super().__init__()

        # populate data and metadata
        self.data = data
        self.name = name
        self._dtype = self.data.dtype
        self._fields = self.data.dtype.names
        self._types = tuple([self.data.dtype.fields[f][0] for f in self.fields])



    # properties
    @property
    def dtype(self):
        return self._dtype
    @dtype.setter
    def dtype(self, dtype):
        self._dtype = dtype

    @property
    def fields(self):
        return self._fields
    @fields.setter
    def fields(self, x):
        self.data.dtype.names = x
        self._fields = x

    @property
    def types(self):
        return self._types

    @property
    def length(self):
        return np.atleast_1d(self.data).shape[0]



    ## Add, remove, sort data

    def add(self, data):
        """
        Appends a numpy structured array. Its dtypes must agree with the existing data.
        """
        assert self.dtype == data.dtype, "Error: dtypes must agree"
        if isinstance(data,PointList):
            data = data.data
        self.data = np.append(self.data, data)

    def remove(self, mask):
        """ Removes points wherever mask==True
        """
        assert np.atleast_1d(mask).shape[0] == self.length, "deletemask must be same length as the data"
        inds = mask.nonzero()[0]
        self.data = np.delete(self.data, inds)

    def sort(self, field, order='ascending'):
        """
        Sorts the point list according to field,
        which must be a field in self.dtype.
        order should be 'descending' or 'ascending'.
        """
        assert field in self.fields
        assert (order=='descending') or (order=='ascending')
        if order=='ascending':
            self.data = np.sort(self.data, order=field)
        else:
            self.data = np.sort(self.data, order=field)[::-1]


    ## Copy, copy+modify PointList

    def copy(self, name=None):
        """ Returns a copy of the PointList. If name=None, sets to `{name}_copy`
        """
        name = name if name is not None else self.name+"_copy"

        pl = PointList(
            data = np.copy(self.data),
            name = name)

        for k,v in self.metadata.items():
            pl.metadata = v.copy(name=k)

        return pl

    def add_fields(self, new_fields, name=''):
        """
        Creates a copy of the PointList, but with additional fields given by new_fields.

        Args:
            new_fields: a list of 2-tuples, ('name', dtype)
            name: a name for the new pointlist
        """
        dtype = []
        for f,t in zip(self.fields,self.types):
            dtype.append((f,t))
        for f,t in new_fields:
            dtype.append((f,t))

        data = np.zeros(self.length, dtype=dtype)
        for f in self.fields:
            data[f] = np.copy(self.data[f])

        return PointList(data=data, name=name)

    def add_data_by_field(self, data, fields=None):
        """
        Add a list of data arrays to the PointList, in the fields
        given by `fields`. If `fields` is not specified, assumes the data
        arrays are in the same order as self.fields

        Args:
            data (list): arrays of data to add to each field
        """

        if data[0].ndim == 0:
            L = 1,
        else:
            L = data[0].shape[0]
        newdata = np.zeros(L,dtype=self.dtype)

        _fields = self.fields if fields is None else fields

        for d,f in zip(data, _fields):
            newdata[f] = d

        self.data = np.append(self.data,newdata)




    ## Representation to standard output
    def __repr__(self):

        space = ' '*len(self.__class__.__name__)+'  '
        string = f"{self.__class__.__name__}( A length {self.length} PointList called '{self.name}',"
        string += "\n"+space+f"with {len(self.fields)} fields:"
        string += "\n"
        space2 = max([len(field) for field in self.fields])+3
        for f,t in zip(self.fields,self.types):
            string += "\n"+space+f"{f}{(space2-len(f))*' '}({str(t)})"
        string += "\n)"

        return string


    # Slicing
    def __getitem__(self, v):
        return self.data[v]



    # HDF5 i/o

    # write
    def to_h5(self,group):
        """
        Takes an h5py Group instance and creates a subgroup containing
        this PointList, tags indicating its EMD type and Python class,
        and the pointlist's data and metadata.

        Accepts:
            group (h5py Group)

        Returns:
            (h5py Group) the new pointlist's group
        """
        # Construct group and add metadata
        grp = Node.to_h5(self,group)

        # Add data
        for f,t in zip(self.fields,self.types):
            group_current_field = grp.create_dataset(
                f,
                data = self.data[f]
            )
            group_current_field.attrs.create("dtype", np.string_(t))

        # Return
        return grp




    # read
    @classmethod
    def _get_constructor_args(cls,group):
        """
        Returns a dictionary of args/values to pass to the class constructor
        """
        # Get PointList metadata
        fields = list(group.keys())
        fields = [f for f in fields if isinstance(group[f],h5py.Dataset)]
        dtype = []
        for field in fields:
            curr_dtype = group[field].attrs["dtype"].decode('utf-8')
            dtype.append((field,curr_dtype))
        length = len(group[fields[0]])

        # Get data
        data = np.zeros(length,dtype=dtype)
        if length > 0:
            for field in fields:
                data[field] = np.array(group[field])

        # make args dictionary and return
        return {
            'data' : data,
            'name' : basename(group.name)
        }



